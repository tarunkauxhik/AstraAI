/** `**strong**` and `*emphasis*`; a lone `*` with a space beside it (as in `a * b`) stays literal. */
const EMPHASIS = /(\*\*[^*]+\*\*|\*[^\s*](?:[^*]*[^\s*])?\*)/

function Emphasis({ text }: { text: string }) {
  return text.split(EMPHASIS).map((part, index) =>
    index % 2 === 0 ? (
      part
    ) : part.startsWith("**") ? (
      <strong key={index} className="font-semibold text-foreground">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <em key={index}>{part.slice(1, -1)}</em>
    ),
  )
}

/**
 * The model's plain-text prose: `code` spans (kept literal) and emphasis, rendered as text
 * only. Nothing is ever interpreted as HTML.
 */
export function InlineText({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/).map((part, index) =>
        part.startsWith("`") && part.endsWith("`") && part.length > 1 ? (
          <code key={index} className="rounded bg-muted px-1 font-mono text-[0.85em] text-foreground">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Emphasis key={index} text={part} />
        ),
      )}
    </>
  )
}
