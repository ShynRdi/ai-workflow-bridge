(() => {
  const providers = [
    {
      id: "chatgpt", name: "ChatGPT", vendor: "OpenAI", status: "stable",
      domains: ["chatgpt.com", "chat.openai.com"],
      origins: ["https://chatgpt.com/*", "https://chat.openai.com/*"],
      composer: ['#prompt-textarea[contenteditable="true"]', '[data-testid="prompt-textarea"][contenteditable="true"]', '#prompt-textarea', 'textarea[name="prompt-textarea"]', 'textarea[data-testid="prompt-textarea"]'],
      assistant: ['[data-message-author-role="assistant"]', 'article[data-testid^="conversation-turn-"] [data-message-author-role="assistant"]'],
      user: ['[data-message-author-role="user"]', 'article[data-testid^="conversation-turn-"] [data-message-author-role="user"]'],
      stop: ['button[data-testid="stop-button"]', '[data-testid="stop-button"]', 'button[aria-label*="Stop generating"]'],
      send: ['#composer-submit-button', 'button[data-testid="send-button"]', 'button[data-testid*="send-button"]', 'button[aria-label="Send prompt"]', 'button[aria-label="Send message"]', 'button.composer-submit-btn']
    },
    {
      id: "claude", name: "Claude", vendor: "Anthropic", status: "beta",
      domains: ["claude.ai"], origins: ["https://claude.ai/*"],
      composer: ['div[contenteditable="true"].ProseMirror', 'fieldset div[contenteditable="true"]', 'div[contenteditable="true"]', 'textarea'],
      assistant: ['[data-is-streaming] .font-claude-response', '[data-testid="assistant-message"]', '.font-claude-response'],
      user: ['[data-testid="user-message"]'],
      stop: ['button[aria-label*="Stop"]', 'button[data-testid*="stop"]'],
      send: ['button[aria-label*="Send"]', 'button[data-testid*="send"]']
    },
    {
      id: "gemini", name: "Gemini", vendor: "Google", status: "beta",
      domains: ["gemini.google.com"], origins: ["https://gemini.google.com/*"],
      composer: ['rich-textarea .ql-editor[contenteditable="true"]', 'div[contenteditable="true"]', 'textarea'],
      assistant: ['model-response', '.model-response-text', 'message-content'],
      user: ['user-query', '.user-query-container'],
      stop: ['button[aria-label*="Stop"]', '[data-test-id*="stop"]'],
      send: ['button[aria-label*="Send"]', 'button[data-test-id*="send"]']
    },
    {
      id: "deepseek", name: "DeepSeek", vendor: "DeepSeek", status: "beta",
      domains: ["chat.deepseek.com"], origins: ["https://chat.deepseek.com/*"],
      composer: ['textarea', 'div[contenteditable="true"]'],
      assistant: ['[class*="ds-markdown"]', '[class*="markdown"]'],
      user: ['[class*="message"]'],
      stop: ['button[aria-label*="Stop"]', 'button[class*="stop"]'],
      send: ['button[aria-label*="Send"]', 'button[class*="send"]']
    },
    {
      id: "grok", name: "Grok", vendor: "xAI", status: "beta",
      domains: ["grok.com"], origins: ["https://grok.com/*"],
      composer: ['textarea', 'div[contenteditable="true"]'],
      assistant: ['[data-testid*="assistant"]', '[class*="message"] [class*="markdown"]'],
      user: ['[data-testid*="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]', 'button[data-testid*="send"]']
    },
    {
      id: "perplexity", name: "Perplexity", vendor: "Perplexity", status: "beta",
      domains: ["www.perplexity.ai", "perplexity.ai"], origins: ["https://www.perplexity.ai/*", "https://perplexity.ai/*"],
      composer: ['textarea', 'div[contenteditable="true"]'],
      assistant: ['[data-testid*="answer"]', '[class*="prose"]'], user: ['[data-testid*="query"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Submit"]', 'button[aria-label*="Send"]']
    },
    {
      id: "mistral", name: "Mistral Vibe", vendor: "Mistral AI", status: "beta",
      domains: ["chat.mistral.ai"], origins: ["https://chat.mistral.ai/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[data-testid*="assistant"]', '[class*="prose"]'], user: ['[data-testid*="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]', 'button[data-testid*="send"]']
    },
    {
      id: "copilot", name: "Microsoft Copilot", vendor: "Microsoft", status: "beta",
      domains: ["copilot.com", "www.copilot.com"], origins: ["https://copilot.com/*", "https://www.copilot.com/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[data-testid*="assistant"]', '[class*="response"]'], user: ['[data-testid*="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]', 'button[data-testid*="submit"]']
    },
    {
      id: "meta", name: "Meta AI", vendor: "Meta", status: "experimental",
      domains: ["www.meta.ai", "meta.ai"], origins: ["https://www.meta.ai/*", "https://meta.ai/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[role="article"]', '[class*="message"]'], user: [],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]']
    },
    {
      id: "poe", name: "Poe", vendor: "Quora", status: "experimental",
      domains: ["poe.com"], origins: ["https://poe.com/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[class*="Message_botMessage"]', '[class*="markdown"]'], user: ['[class*="Message_humanMessage"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]']
    },
    {
      id: "qwen", name: "Qwen", vendor: "Alibaba Cloud", status: "experimental",
      domains: ["chat.qwen.ai", "qwen.ai"], origins: ["https://chat.qwen.ai/*", "https://qwen.ai/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[data-role="assistant"]', '[class*="markdown"]'], user: ['[data-role="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]']
    },
    {
      id: "glm", name: "Z.ai / GLM", vendor: "Z.ai", status: "beta",
      domains: ["chat.z.ai", "z.ai"], origins: ["https://chat.z.ai/*", "https://z.ai/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[data-message-role="assistant"]', '[class*="markdown"]'], user: ['[data-message-role="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]']
    },
    {
      id: "kimi", name: "Kimi", vendor: "Moonshot AI", status: "experimental",
      domains: ["www.kimi.com", "kimi.com"], origins: ["https://www.kimi.com/*", "https://kimi.com/*"],
      composer: ['textarea', 'div[contenteditable="true"]'], assistant: ['[data-role="assistant"]', '[class*="markdown"]'], user: ['[data-role="user"]'],
      stop: ['button[aria-label*="Stop"]'], send: ['button[aria-label*="Send"]']
    }
  ];

  function normalizeHost(host) { return String(host || "").toLowerCase().replace(/^www\./, ""); }
  function detectProvider(host) {
    const normalized = normalizeHost(host);
    return providers.find((p) => p.domains.some((d) => {
      const target = normalizeHost(d);
      return normalized === target || normalized.endsWith(`.${target}`);
    })) || null;
  }
  function getProvider(id) { return providers.find((p) => p.id === id) || null; }
  function allOrigins() { return [...new Set(providers.flatMap((p) => p.origins))]; }
  globalThis.AWB_PROVIDERS = providers;
  globalThis.AWB_PROVIDER_UTILS = { normalizeHost, detectProvider, getProvider, allOrigins };
})();
