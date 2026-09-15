# Web LLM Provider Adapters

## Support levels

- **Stable**: used as the primary regression target.
- **Beta**: provider/domain supported with dedicated selectors plus generic fallbacks; provider UI changes may require maintenance.
- **Experimental**: registry/injection/selector support exists, but long autonomous runs should be supervised until validated on the current UI.

## Registry

| Adapter ID | Provider | Status |
|---|---|---|
| chatgpt | ChatGPT / OpenAI | Stable |
| claude | Claude / Anthropic | Beta |
| gemini | Gemini / Google | Beta |
| deepseek | DeepSeek | Beta |
| grok | Grok / xAI | Beta |
| perplexity | Perplexity | Beta |
| mistral | Mistral Vibe | Beta |
| copilot | Microsoft Copilot | Beta |
| glm | Z.ai / GLM | Beta |
| meta | Meta AI | Experimental |
| poe | Poe | Experimental |
| qwen | Qwen | Experimental |
| kimi | Kimi | Experimental |

## Adapter contract

A browser provider adapter needs to identify:

- supported domains/origins;
- prompt composer selectors;
- assistant-message selectors;
- user-message selectors when available;
- stop/generating controls;
- send controls.

The generic content layer then handles:

- text insertion;
- submission verification;
- response stability detection;
- download candidate discovery;
- provider security alert detection.

## Adding a provider

Edit `extension/providers.js` and add a provider entry. Also add its origin to `optional_host_permissions` in `manifest.json`.

Start it as Experimental. Test manually:

1. permission grant;
2. ping/composer discovery;
3. prompt insertion;
4. prompt submission confirmation;
5. streaming detection;
6. completed response capture;
7. second-turn loop;
8. pause/resume;
9. rate/security alert behavior;
10. attachment handling if applicable.

Only promote the adapter after regression testing the current provider UI.
