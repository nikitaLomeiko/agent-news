window.AGENT_NEWS_STATIC = true;
window.AGENT_NEWS_READY = new Promise((resolve) => {
  document.addEventListener("DOMContentLoaded", () => {
    const gate = document.querySelector("#authGate");
    const form = document.querySelector("#authForm");
    const input = document.querySelector("#authPassword");
    const error = document.querySelector("#authError");
    const sessionKey = "agent-news-pages-auth-v1";
    const salt = "agent-news-pages-2026-v1";
    const expected = "62adda8872b4e9ce9eb75b934fb2e247e6f209cd3228cf0f6a4638b58f0058a9";

    if (sessionStorage.getItem(sessionKey) === expected) {
      gate.hidden = true;
      resolve();
      return;
    }

    gate.hidden = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.textContent = "";
      const bytes = new TextEncoder().encode(salt + input.value);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const actual = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
      if (actual === expected) {
        sessionStorage.setItem(sessionKey, expected);
        input.value = "";
        gate.hidden = true;
        resolve();
      } else {
        error.textContent = "Неверный пароль";
        input.select();
      }
    });
  });
});
