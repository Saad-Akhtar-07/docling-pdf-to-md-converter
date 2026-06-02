function normalizeOutsideCodeBlocks(markdown, transformLine) {
  let insideFence = false;

  return markdown
    .split("\n")
    .map((line) => {
      if (/^\s*```/.test(line)) {
        insideFence = !insideFence;
        return line;
      }

      return insideFence ? line : transformLine(line);
    })
    .join("\n");
}

export function postProcessMarkdown(markdown) {
  if (!markdown) return "";

  const normalizedLineEndings = markdown.replace(/\r\n?/g, "\n");

  const normalizedSpaces = normalizeOutsideCodeBlocks(normalizedLineEndings, (line) => {
    if (/^\s*\|.*\|\s*$/.test(line)) return line.trimEnd();
    return line.replace(/[ \t]{2,}/g, " ").trimEnd();
  });

  return normalizedSpaces.replace(/\n{3,}/g, "\n\n").trim();
}
