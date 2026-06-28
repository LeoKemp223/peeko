const response = await fetch(
    `${process.env.LLM_BASE_URL}/chat/completions`,
    {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${process.env.LLM_API_KEY}`
        },
        body: JSON.stringify({
            model: process.env.LLM_MODEL,
            messages: [
                {
                    role: "user",
                    content: prompt
                }
            ]
        })
    }
);

const data = await response.json();

const result = data.choices[0].message.content;
