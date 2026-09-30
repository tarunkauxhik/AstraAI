/**
 * Mirrors backend/app/repository.py parse_repository for immediate feedback: GitHub
 * repository addresses become owner/name, anything else is refused. The server rechecks.
 */

const OWNER = /^(?=.{1,39}$)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$/
const NAME = /^[A-Za-z0-9._-]{1,100}$/
const GITHUB_HOSTS = new Set(["github.com", "www.github.com"])

/** `owner/name` for a GitHub repository address, or null for anything else. */
export function parseRepository(text: string): string | null {
  const value = text.trim()
  let path: string
  if (value.includes("://")) {
    let url: URL
    try {
      url = new URL(value)
    } catch {
      return null
    }
    const plain = url.port === "" && url.username === "" && url.search === "" && url.hash === ""
    if (!["https:", "http:"].includes(url.protocol) || !GITHUB_HOSTS.has(url.hostname) || !plain) {
      return null
    }
    path = url.pathname
  } else if (GITHUB_HOSTS.has(value.split("/")[0])) {
    path = value.slice(value.indexOf("/") + 1)
  } else {
    path = value
  }
  // One leading and one trailing slash at most; an empty segment anywhere is refused.
  path = path.replace(/^\//, "").replace(/\/$/, "").replace(/\.git$/, "")
  const [owner, name, ...rest] = path.split("/")
  if (rest.length > 0 || !OWNER.test(owner) || name === undefined || !NAME.test(name)) return null
  if (name === "." || name === "..") return null
  return `${owner}/${name}`
}
