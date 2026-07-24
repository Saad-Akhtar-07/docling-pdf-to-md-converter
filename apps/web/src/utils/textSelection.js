// Maps the browser's current text Selection to a plain (start, end) character
// offset within `containerEl`'s rendered text -- used by the plan review
// page's source panel to let a reviewer select real slide text and re-anchor
// an evidence idea to it. A block's text can already contain <mark> spans
// (existing highlighted anchors), which splits it across multiple text
// nodes, so this walks every text node under containerEl in document order
// rather than assuming the selection sits inside a single node.
export function getSelectionOffsetsWithin(containerEl) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;

  const range = selection.getRangeAt(0);
  if (!containerEl.contains(range.commonAncestorContainer)) return null;

  function offsetOf(node, nodeOffset) {
    const walker = document.createTreeWalker(containerEl, NodeFilter.SHOW_TEXT);
    let total = 0;
    let current = walker.nextNode();
    while (current) {
      if (current === node) return total + nodeOffset;
      total += current.textContent.length;
      current = walker.nextNode();
    }
    return total;
  }

  const start = offsetOf(range.startContainer, range.startOffset);
  const end = offsetOf(range.endContainer, range.endOffset);
  const text = selection.toString();
  if (start === end || !text.trim()) return null;

  return { start: Math.min(start, end), end: Math.max(start, end), text };
}
