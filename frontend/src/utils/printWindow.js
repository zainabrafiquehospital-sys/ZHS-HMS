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

    // Use full viewport dimensions with opacity 0 so Chrome's print engine
    // calculates proper layout bounds, while keeping it invisible to the user.
    iframe.style.position = 'fixed';
    iframe.style.top = '0';
    iframe.style.left = '0';
    iframe.style.width = '100%';
    iframe.style.height = '100%';
    iframe.style.border = '0';
    iframe.style.opacity = '0';
    iframe.style.pointerEvents = 'none';
    iframe.style.zIndex = '-9999';
    iframe.setAttribute('aria-hidden', 'true');

    let settled = false;
    let blobUrl = null;

    function cleanup() {
      setTimeout(() => {
        if (blobUrl) {
          URL.revokeObjectURL(blobUrl);
        }
        iframe.parentNode?.removeChild(iframe);
      }, 1500);
    }

    const triggerPrint = () => {
      if (settled) return;
      settled = true;

      const win = iframe.contentWindow;
      if (!win) {
        reject(new Error('Print iframe window not accessible'));
        cleanup();
        return;
      }

      // Allow two animation frames for complete DOM paint and asset rendering
      win.requestAnimationFrame(() => {
        win.requestAnimationFrame(() => {
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

    // Use Blob URL approach for clean, isolated loading without about:blank race conditions
    try {
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
      blobUrl = URL.createObjectURL(blob);
      iframe.onload = triggerPrint;
      iframe.src = blobUrl;
      document.body.appendChild(iframe);
    } catch {
      // Fallback for environments where Blob URL is restricted
      document.body.appendChild(iframe);
      const frameDocument = iframe.contentDocument ?? iframe.contentWindow.document;
      frameDocument.open();
      frameDocument.write(html);
      frameDocument.close();

      if (frameDocument.readyState === 'complete') {
        triggerPrint();
      } else {
        iframe.onload = triggerPrint;
      }
    }
  });
}

