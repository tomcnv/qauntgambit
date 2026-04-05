/**
 * Bot sub-page URL parsing utilities.
 *
 * Bot sub-page URLs follow the pattern: /bot/{bot_id}/{sub_page}
 * e.g. /bot/abc-123/decisions, /bot/my-bot/positions
 */

export interface BotSubPageContext {
  botId: string;
  subPage: string;
}

/**
 * Extract bot identifier and sub-page from a bot sub-page URL.
 * Returns null if the path does not match the /bot/{bot_id}/{sub_page} pattern.
 */
export function parseBotSubPageUrl(path: string): BotSubPageContext | null {
  const match = path.match(/^\/bot\/([^/]+)\/([^/]+)$/);
  if (!match) return null;
  return { botId: match[1], subPage: match[2] };
}
