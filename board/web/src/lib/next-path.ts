export function nextPath(requested: string | null): string {
  if (requested === null || requested === "" || requested === "/") {
    return "/board";
  }
  if (!requested.startsWith("/") || requested.startsWith("//")) {
    return "/board";
  }
  return requested;
}