// The site works without this script: every form posts and the page reloads with a note. With it, a server
// chosen in the picker applies at once, and a switch or settings form saves in place, showing what happened
// beside it.
(() => {
  function choose(select) {
    select.addEventListener("change", () => select.form.submit());
  }

  function show(form, text, bad) {
    const result = form.querySelector(".result");
    if (!result) return;
    result.textContent = text;
    result.classList.toggle("bad", bad);
  }

  // A switch's button and its form's address follow the plugin's new state.
  function flip(form, state) {
    const button = form.querySelector("button");
    const on = state === "enabled";
    button.textContent = on ? "On" : "Off";
    button.className = on ? "on" : "off";
    button.setAttribute("aria-pressed", on ? "true" : "false");
    form.action = form.action.replace(/\/(enable|disable)$/, on ? "/disable" : "/enable");
  }

  async function save(event) {
    const form = event.currentTarget;
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    try {
      const reply = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const done = await reply.json();
      if (done.state) flip(form, done.state);
      show(form, done.message, !done.ok);
    } catch {
      show(form, "That did not reach the server. Try again.", true);
    } finally {
      button.disabled = false;
    }
  }

  document.querySelectorAll("select[data-autosubmit]").forEach(choose);
  document.querySelectorAll("form[data-enhance]").forEach((form) => form.addEventListener("submit", save));
})();
