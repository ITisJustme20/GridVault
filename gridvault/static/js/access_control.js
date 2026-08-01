(() => {
    "use strict";

    const button = document.querySelector("[data-copy-target]");
    if (!button) return;
    const status = document.querySelector("[data-copy-status]");
    button.addEventListener("click", async () => {
        const target = document.getElementById(button.dataset.copyTarget);
        if (!target) return;
        try {
            await navigator.clipboard.writeText(target.textContent.trim());
            if (status) status.textContent = "Authorization code copied.";
        } catch (_error) {
            if (status) status.textContent = "Copy failed. Select and copy the code manually.";
        }
    });
})();
