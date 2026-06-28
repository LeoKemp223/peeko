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

function requireEnv() {
    const missing = REQUIRED_ENV.filter((name) => !process.env[name]);
    if (missing.length > 0) {
        throw new Error(`Missing required environment variables: ${missing.join(", ")}`);
    }
}

function readEvent() {
    const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
    if (!event.pull_request) {
        throw new Error("This workflow only supports pull_request events.");
    }
    return event;
}

function githubHeaders(extra = {}) {
    return {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
        "User-Agent": "peeko-ai-review",
        "X-GitHub-Api-Version": "2022-11-28",
        ...extra,
    };
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            ...githubHeaders(),
            ...(options.headers || {}),
        },
    });

    const text = await response.text();
    let data;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = text;
    }

    if (!response.ok) {
        throw new Error(`GitHub API request failed (${response.status}): ${JSON.stringify(data)}`);
    }

    return data;
}

async function fetchPullRequestFiles(owner, repo, pullNumber) {
    const files = [];

    for (let page = 1; page <= 30; page += 1) {
        const url = `https://api.github.com/repos/${owner}/${repo}/pulls/${pullNumber}/files?per_page=100&page=${page}`;
        const pageFiles = await fetchJson(url);
        files.push(...pageFiles);

        if (pageFiles.length < 100) {
            break;
        }
    }

    return files;
}

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

function buildPrompt(event, files) {
    const pr = event.pull_request;
    const diff = formatDiff(files);

    return [
        "You are reviewing a GitHub pull request for the peeko repository.",
        "Focus on bugs, regressions, security issues, maintainability risks, and missing tests.",
        "Be concise. If there are no meaningful issues, say so clearly.",
        "Prefer actionable comments with file paths and line references when possible.",
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
                    content: "You are a careful senior engineer performing a pull request review.",
                },
                {
                    role: "user",
                    content: prompt,
                },
            ],
        }),
    });

    const text = await response.text();
    let data;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = text;
    }

    if (!response.ok) {
        throw new Error(`LLM API request failed (${response.status}): ${JSON.stringify(data)}`);
    }

    const result = data?.choices?.[0]?.message?.content;
    if (!result) {
        throw new Error(`LLM API response did not include choices[0].message.content: ${JSON.stringify(data)}`);
    }

    return result.trim();
}

async function postPrComment(owner, repo, pullNumber, review) {
    const url = `https://api.github.com/repos/${owner}/${repo}/issues/${pullNumber}/comments`;
    const body = [
        "## AI Code Review",
        "",
        review,
        "",
        "<sub>Generated by GitHub Actions.</sub>",
    ].join("\n");

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
