(() => {
  const PROVISIONAL_PATHS = new Set([
    "/",
    "/new",
    "/chat",
    "/chat/new",
    "/new-chat",
    "/app",
  ]);

  function normalizeConversationPath(url = "") {
    const parsed = new URL(String(url || ""));

    let pathname = parsed.pathname || "/";

    pathname = pathname.replace(/\/{2,}/g, "/");

    if (pathname.length > 1) {
      pathname = pathname.replace(/\/+$/, "");
    }

    return pathname || "/";
  }

  function isProvisionalConversationPath(pathname = "") {
    const value = String(pathname || "/");

    return PROVISIONAL_PATHS.has(value);
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

    const pathname = normalizeConversationPath(url);

    return {
      version: 1,
      provider,
      pathname,
      key: `${provider}:${pathname}`,
      provisional:
        isProvisionalConversationPath(pathname),
    };
  }

  globalThis.AWB_CONVERSATION_IDENTITY = {
    normalizeConversationPath,
    isProvisionalConversationPath,
    conversationIdentity,
  };
})();
