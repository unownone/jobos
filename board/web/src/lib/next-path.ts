const APP_ORIGIN = "http://jobos.local";

function decodedPathname(pathname: string): string | null {
  try {
    return decodeURIComponent(pathname);
  } catch {
    return null;
  }
}

export function nextPath(requested: string | null): string {
  if (requested === null || requested === "" || requested === "/" || requested === "/start") {
    return "/board";
  }

  let url: URL;
  try {
    url = new URL(requested, APP_ORIGIN);
  } catch {
    return "/board";
  }
  if (url.origin !== APP_ORIGIN) {
    return "/board";
  }

  const decoded = decodedPathname(url.pathname);
  if (
    decoded === null ||
    !decoded.startsWith("/") ||
    decoded.startsWith("//") ||
    decoded.includes("\\") ||
    decoded.includes("\0")
  ) {
    return "/board";
  }
  if (decoded === "/" || decoded === "/start") {
    return "/board";
  }

  return `${url.pathname}${url.search}${url.hash}`;
}