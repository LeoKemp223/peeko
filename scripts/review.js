const fs = require("node:fs");

const REQUIRED_ENV = [
    "GITHUB_EVENT_PATH",
    "GITHUB_REPOSITORY",
    "GITHUB_TOKEN",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
];

const MAX_DIFF_CHARS = 60000;
const MAX_PR_FILE_PAGES = 30;

// 嵌入式项目专用审查规则；这些内容会随 PR diff 一起发给 LLM。
const EMBEDDED_REVIEW_RULES = [
    "你正在审查 peeko 仓库的 GitHub Pull Request。peeko 是一个面向嵌入式开发的工具链项目。",
    "请以资深嵌入式固件工程师和 MCU 工具链工程师的视角进行代码审查。",
    "重点关注嵌入式开发中真正重要的问题：",
    "- MCU RAM/Flash 布局假设、链接脚本/map/ELF 解析风险，以及符号解析正确性。",
    "- 串口协议正确性、帧格式、超时处理、半包/粘包、读写重试，以及主机与设备状态同步。",
    "- C 固件安全性：缓冲区边界、整数宽度和有符号问题、内存对齐、端序假设、volatile/共享状态、ISR 安全性和可重入性。",
    "- Python 上位机工具可靠性：二进制解析、串口资源释放、跨平台行为、CLI 错误处理，以及依赖和运行时兼容性。",
    "- 实时性和硬件风险：阻塞调用、时序假设、watchdog 影响、电源/复位行为，以及必须上板验证的行为。",
    "- 构建和发布风险：打包、生成产物、工具链假设、缺失测试，以及可能误导嵌入式用户的文档。",
    "不要编造 diff 中没有出现的开发板型号、MCU 类型、寄存器映射、引脚定义、串口参数或硬件行为。",
    "如果某个问题依赖未知硬件细节，请明确说明你的假设，并指出需要补充哪些证据。",
    "请保持简洁。如果没有发现有意义的嵌入式开发问题，请明确说明。",
    "尽量给出可执行的建议，并在可能时标注文件路径和行号。",
    "最终审查结果必须使用中文输出。",
];

function requireEnv() {
    const missing = REQUIRED_ENV.filter((name) => !process.env[name]);
    if (missing.length > 0) {
        throw new Error(`Missing required environment variables: ${missing.join(", ")}`);
    }
}

// GitHub Actions 会把触发事件写入 GITHUB_EVENT_PATH，这里读取 PR 元信息。
function readEvent() {
    const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
    if (!event.pull_request) {
        throw new Error("This workflow only supports pull_request events.");
    }
    return event;
}

function githubHeaders() {
    return {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
        "User-Agent": "peeko-ai-review",
        "X-GitHub-Api-Version": "2022-11-28",
    };
}

// GitHub API 和 LLM API 都可能返回 JSON 或纯文本错误，统一解析便于报错。
async function readResponseBody(response) {
    const text = await response.text();
    try {
        return text ? JSON.parse(text) : null;
    } catch {
        return text;
    }
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            ...githubHeaders(),
            ...(options.headers || {}),
        },
    });

    const data = await readResponseBody(response);
    if (!response.ok) {
        throw new Error(`GitHub API request failed (${response.status}): ${JSON.stringify(data)}`);
    }

    return data;
}

// GitHub 的 PR files 接口分页返回，每页最多 100 个文件。
async function fetchPullRequestFiles(owner, repo, pullNumber) {
    const files = [];

    for (let page = 1; page <= MAX_PR_FILE_PAGES; page += 1) {
        const url = `https://api.github.com/repos/${owner}/${repo}/pulls/${pullNumber}/files?per_page=100&page=${page}`;
        const pageFiles = await fetchJson(url);
        files.push(...pageFiles);

        if (pageFiles.length < 100) {
            break;
        }
    }

    return files;
}

// 控制发送给 LLM 的 diff 大小，避免大 PR 超过模型上下文或接口限制。
function formatDiff(files) {
    const sections = files.map((file) => {
        const patch = file.patch || "[Binary file or patch unavailable]";
        return [
            `File: ${file.filename}`,
            `Status: ${file.status}`,
            `Changes: +${file.additions} -${file.deletions}`,
            "Patch:",
            patch,
        ].join("\n");
    });

    const diff = sections.join("\n\n---\n\n");
    if (diff.length <= MAX_DIFF_CHARS) {
        return diff;
    }

    return `${diff.slice(0, MAX_DIFF_CHARS)}\n\n[Diff truncated to ${MAX_DIFF_CHARS} characters]`;
}

// 组合审查规则、PR 描述、文件列表和 diff，形成最终用户提示词。
function buildPrompt(event, files) {
    const pr = event.pull_request;
    const diff = formatDiff(files);

    return [
        ...EMBEDDED_REVIEW_RULES,
        "",
        `PR title: ${pr.title}`,
        `PR author: ${pr.user.login}`,
        `Base branch: ${pr.base.ref}`,
        `Head branch: ${pr.head.ref}`,
        "",
        "PR description:",
        pr.body || "(No description provided)",
        "",
        "Changed files:",
        files.map((file) => `- ${file.filename} (${file.status}, +${file.additions}/-${file.deletions})`).join("\n") || "(No files changed)",
        "",
        "Diff:",
        "```diff",
        diff,
        "```",
    ].join("\n");
}

async function callLlm(prompt) {
    const baseUrl = process.env.LLM_BASE_URL.replace(/\/+$/, "");
    const response = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${process.env.LLM_API_KEY}`,
        },
        body: JSON.stringify({
            model: process.env.LLM_MODEL,
            messages: [
                {
                    role: "system",
                    content: "你是一名严谨的资深嵌入式固件工程师和 MCU 工具链工程师，正在进行 Pull Request 代码审查。最终审查结果必须使用中文输出。",
                },
                {
                    role: "user",
                    content: prompt,
                },
            ],
        }),
    });

    const data = await readResponseBody(response);
    if (!response.ok) {
        throw new Error(`LLM API request failed (${response.status}): ${JSON.stringify(data)}`);
    }

    const result = data?.choices?.[0]?.message?.content;
    if (!result) {
        throw new Error(`LLM API response did not include choices[0].message.content: ${JSON.stringify(data)}`);
    }

    return result.trim();
}

// PR 评论走 issue comments API；这里不会创建 GitHub review，也不会阻断合并。
async function postPrComment(owner, repo, pullNumber, review) {
    const url = `https://api.github.com/repos/${owner}/${repo}/issues/${pullNumber}/comments`;
    const body = `## AI Code Review

${review}

<sub>Generated by GitHub Actions.</sub>`;

    await fetchJson(url, {
        method: "POST",
        body: JSON.stringify({ body }),
    });
}

async function main() {
    requireEnv();

    const event = readEvent();
    const [owner, repo] = process.env.GITHUB_REPOSITORY.split("/");
    if (!owner || !repo) {
        throw new Error(`Invalid GITHUB_REPOSITORY value: ${process.env.GITHUB_REPOSITORY}`);
    }

    const pullNumber = event.pull_request.number;

    console.log(`Reviewing PR #${pullNumber} in ${owner}/${repo}`);

    const files = await fetchPullRequestFiles(owner, repo, pullNumber);
    const prompt = buildPrompt(event, files);
    const review = await callLlm(prompt);

    await postPrComment(owner, repo, pullNumber, review);
    console.log("AI review comment posted.");
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
