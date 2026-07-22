const URL_PATTERN = /https?:\/\/[^\s<>"']+/i;
const TRAILING_PUNCTUATION = /[.,;:!?\])}>，。；：！？）】》」』]+$/u;

export function extractHttpUrl(text: string): string | null {
  const match = text.match(URL_PATTERN);
  if (!match) return null;
  const value = match[0].replace(TRAILING_PUNCTUATION, "");
  return value || null;
}
