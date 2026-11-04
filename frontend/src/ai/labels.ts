/** How a provider is written for people. */
const PROVIDERS: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic', ollama: 'Ollama' }

export const providerLabel = (name: string): string => PROVIDERS[name] ?? name.charAt(0).toUpperCase() + name.slice(1)
