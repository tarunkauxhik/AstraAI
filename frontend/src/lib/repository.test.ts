import { describe, expect, it } from "vitest"

import { parseRepository } from "@/lib/repository"

describe("repository address", () => {
  it.each([
    "octo/sample",
    "https://github.com/octo/sample",
    "https://github.com/octo/sample/",
    "https://github.com/octo/sample.git",
    "http://github.com/octo/sample",
    "https://www.github.com/octo/sample",
    "github.com/octo/sample",
    "  https://github.com/octo/sample  ",
  ])("accepts %s as octo/sample", (text) => {
    expect(parseRepository(text)).toBe("octo/sample")
  })

  it.each([
    "",
    "octo",
    "https://gitlab.com/octo/sample",
    "https://github.com.evil.com/octo/sample",
    "https://evil.com/github.com/octo/sample",
    "https://github.com/octo/sample/tree/main",
    "https://github.com/octo/sample?tab=readme",
    "https://github.com/octo/sample#readme",
    "https://user@github.com/octo/sample",
    "https://github.com:8443/octo/sample",
    "git@github.com:octo/sample.git",
    "octo/..",
    "-octo/sample",
    "octo/sam ple",
    "https://github.com//octo/sample",
  ])("refuses %s", (text) => {
    expect(parseRepository(text)).toBeNull()
  })
})
