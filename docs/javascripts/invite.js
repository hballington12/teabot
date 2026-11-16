// Two buttons in the header, on every page: one that adds the public teabot to a server, and one that opens the
// plugin hub. Added with a script rather than by replacing the theme's header template, so the theme updates
// without our copy falling behind.
(() => {
  const INVITE = "https://discord.com/oauth2/authorize?client_id=1570928156100264097&scope=bot+applications.commands&permissions=8";

  // The hub's address, made absolute: each page names the site's root relative to itself, and the header outlives
  // page changes, so a relative link would go wrong after the first.
  function hubAddress() {
    const config = document.getElementById("__config");
    const base = config ? JSON.parse(config.textContent || "{}").base || "." : ".";
    return new URL(`${base}/hub/`, window.location.href).href;
  }

  function button(className, href, label, title) {
    const link = document.createElement("a");
    link.className = className;
    link.href = href;
    link.textContent = label;
    link.title = title;
    return link;
  }

  function add() {
    const header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".teabot-header-invite")) return;
    const search = header.querySelector(".md-search") || header.querySelector("[for=__search]");
    const before = search ? search : null;
    header.insertBefore(button("teabot-header-hub", hubAddress(), "Plugin hub", "Browse Teabot's plugins"), before);
    header.insertBefore(button("teabot-header-invite", INVITE, "Add Teabot", "Add Teabot to your Discord guild"), before);
  }

  if (window.document$) window.document$.subscribe(add);
  else document.addEventListener("DOMContentLoaded", add);
})();
