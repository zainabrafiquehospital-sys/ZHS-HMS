/** Opens a blank popup, writes a fully self-contained HTML document into
 * it, and sends it through the browser's native print pipeline —
 * shared by every print flow in this app (Reception's registration slip,
 * Billing's invoice receipt, Admin's leads sheet) that builds a
 * print-ready document and needs it on paper via `window.print()`.
 *
 * The previous version of this (duplicated three times, one per feature)
 * called `printWindow.print()` synchronously, on the very next line
 * after `document.write()`/`document.close()`. That's a real, proven
 * race condition, not a theoretical one: `document.write()` starts
 * parsing/layout asynchronously, and calling `.print()` before a layout
 * + paint pass has actually completed can hand the browser's print
 * engine a snapshot of an unpainted page — the interactive preview looks
 * completely correct because by the time a human actually looks at it,
 * the async layout has long since caught up, but the print engine's
 * capture already happened. This is exactly consistent with "preview
 * shows everything correctly, physical output is blank": the two are
 * rendering at different points in time, not from different content.
 *
 * Fix: wait for the popup's own `load` event (fires once
 * `document.write`'s content has finished parsing, the same as a normal
 * navigation), then wait two animation-frame callbacks — the standard,
 * widely-used pattern for guaranteeing at least one full render/paint
 * cycle has actually been committed before printing. `load` alone is
 * not sufficient in every browser; the double-rAF closes that gap.
 */
export function openAndPrintHtml(html) {
  const printWindow = window.open('', '_blank');
  if (!printWindow) {
    throw new Error('Unable to open print window — check your browser popup settings.');
  }

  printWindow.document.write(html);
  printWindow.document.close();

  return new Promise((resolve, reject) => {
    printWindow.onload = () => {
      printWindow.requestAnimationFrame(() => {
        printWindow.requestAnimationFrame(() => {
          try {
            printWindow.focus();
            printWindow.print();
            resolve();
          } catch (error) {
            reject(error);
          }
        });
      });
    };
  });
}
