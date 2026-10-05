(() => {
  const ROUTE_RULES = {
    chatgpt: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/c\/[^/]+$/,
      ],
    },

    claude: {
      provisional: new Set(["/", "/new"]),
      conversation: [
        /^\/chat\/[^/]+$/,
      ],
    },

    gemini: {
      provisional: new Set(["/", "/app"]),
      conversation: [
        /^\/app\/[^/]+$/,
      ],
    },

    deepseek: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/a\/chat\/s\/[^/]+$/,
      ],
    },

    grok: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/c\/[^/]+$/,
      ],
    },

    perplexity: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/search\/[^/]+$/,
      ],
    },

    mistral: {
      provisional: new Set(["/", "/chat"]),
      conversation: [
        /^\/chat\/[^/]+$/,
      ],
    },

    copilot: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/chats\/[^/]+$/,
      ],
    },

    qwen: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/chat\/[^/]+$/,
      ],
    },

    kimi: {
      provisional: new Set(["/"]),
      conversation: [
        /^\/chat\/[^/]+$/,
      ],
    },
  };

  const DEFAULT_PROVISIONAL_PATHS =
    new Set(["/"]);

  function normalizePathname(pathname = "/") {
    let value = String(
      pathname || "/",
    );

    if (!value.startsWith("/")) {
      value = `/${value}`;
    }

    value = value.replace(
      /\/{2,}/g,
      "/",
    );

    if (value.length > 1) {
      value = value.replace(
        /\/+$/,
        "",
      );
    }

    return value || "/";
  }

  function normalizeConversationPath(url = "") {
    const parsed = new URL(
      String(url || ""),
    );

    return normalizePathname(
      parsed.pathname || "/",
    );
  }

  function classifyConversationPath(
    providerId,
    pathname,
  ) {
    const provider = String(
      providerId || "",
    ).trim();

    const value = normalizePathname(
      pathname,
    );

    const rules =
      ROUTE_RULES[provider] || null;

    const provisional =
      rules?.provisional ||
      DEFAULT_PROVISIONAL_PATHS;

    if (provisional.has(value)) {
      return "provisional";
    }

    if (
      rules?.conversation?.some(
        (pattern) => pattern.test(value),
      )
    ) {
      return "conversation";
    }

    return "other";
  }

  function isProvisionalConversationPath(
    pathname = "",
    providerId = "",
  ) {
    return (
      classifyConversationPath(
        providerId,
        pathname,
      ) === "provisional"
    );
  }

  function conversationIdentity(
    providerId,
    url,
  ) {
    const provider = String(
      providerId || "",
    ).trim();

    if (!provider) {
      throw new Error(
        "Conversation identity requires a provider id",
      );
    }

    const pathname =
      normalizeConversationPath(url);

    const kind =
      classifyConversationPath(
        provider,
        pathname,
      );

    return {
      version: 1,
      provider,
      pathname,
      key: `${provider}:${pathname}`,
      kind,
      provisional:
        kind === "provisional",
      autoSealable:
        kind === "conversation",
    };
  }

  globalThis.AWB_CONVERSATION_IDENTITY = {
    normalizeConversationPath,
    classifyConversationPath,
    isProvisionalConversationPath,
    conversationIdentity,
  };
})();
