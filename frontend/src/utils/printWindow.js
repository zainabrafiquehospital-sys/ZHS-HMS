/** Renders a fully self-contained HTML document into a hidden `<iframe>`
 * appended to the current page, then sends it through the browser's
 * native print pipeline — shared by every print flow in this app
 * (Reception's registration slip, Billing's invoice receipt, Admin's
 * leads sheet) that builds a print-ready document and needs it on
 * paper via `.print()`.
 *
 * History, for whoever touches this next:
 *
 * v1 called `printWindow.print()` synchronously, on the very next line
 * after `document.write()`/`document.close()` on a `window.open()`
 * popup. Proven race condition: `document.write()` lays out
 * asynchronously, and calling `.print()` before layout+paint actually
 * completed handed the print engine a snapshot of an unpainted page —
 * "preview looks correct, physical output is blank" (fixed in fc39082).
 *
 * v2 fixed that specific race (wait for the popup's `load` event, then
 * two requestAnimationFrame callbacks before printing) but kept the
 * `window.open()` popup itself. That version was verified working
 * end-to-end against production with a real headless-browser
 * reproduction — window.open() not blocked, document.write() content
 * rendered correctly, load fired, print() was genuinely invoked — and
 * printing was *still* reported broken in real-world use. A second
 * browsing context (the popup) not gaining real screen focus in a
 * visible foreground window is a plausible, well-documented failure
 * mode for window.open()-based printing that a headless reproduction
 * cannot observe (no real screen to lose focus on) — modern Chrome has
 * gotten progressively more aggressive about not letting
 * window.open()-created windows steal focus/foreground a background
 * tab, and that class of behavior can change under an ordinary browser
 * auto-update with zero application-code changes.
 *
 * v3 (this version) removes the second browsing context entirely:
 * render into a hidden iframe appended to the *current*, already-
 * focused page instead of a new window. `.print()` on the iframe's
 * own contentWindow prints in the tab the user is already looking at
 * — there is no separate window to lose focus, and no popup blocker
 * to trigger in the first place (iframes appended to the DOM are not
 * subject to popup blocking at all). This is the standard, widely-used
 * pattern for programmatic printing for exactly this reason.
 */
export function openAndPrintHtml(html) {
  return new Promise((resolve, reject) => {
    const iframe = document.createElement('iframe');
    // Visually hidden but NOT display:none — some browsers skip
    // painting (and therefore printing) a display:none iframe's
    // content, or never fire its load event reliably. Zero-sized and
    // off-screen achieves the same "invisible to the user" result
    // without that risk.
    iframe.style.position = 'fixed';
    iframe.style.right = '0';
    iframe.style.bottom = '0';
    iframe.style.width = '0';
    iframe.style.height = '0';
    iframe.style.border = '0';
    iframe.setAttribute('aria-hidden', 'true');

    let settled = false;

    function cleanup() {
      // Delayed, not immediate: `.print()` returns synchronously from
      // JS's perspective, but the browser's print pipeline can still be
      // reading from the frame asynchronously after that call returns —
      // removing the iframe too eagerly has been known to cancel an
      // in-flight print job in some browsers.
      setTimeout(() => {
        iframe.parentNode?.removeChild(iframe);
      }, 1000);
    }

    iframe.onload = () => {
      if (settled) return; // guards against a stray second load event
      const win = iframe.contentWindow;
      // Same double-rAF margin as the previous window.open()-based
      // version, for the same reason — `load` firing doesn't guarantee
      // a paint has actually been committed yet in every browser.
      win.requestAnimationFrame(() => {
        win.requestAnimationFrame(() => {
          settled = true;
          try {
            win.focus();
            win.print();
            resolve();
          } catch (error) {
            reject(error);
          } finally {
            cleanup();
          }
        });
      });
    };

    document.body.appendChild(iframe);
    const frameDocument = iframe.contentDocument ?? iframe.contentWindow.document;
    frameDocument.open();
    frameDocument.write(html);
    frameDocument.close();
  });
}
