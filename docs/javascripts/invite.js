// A button in the header, on every page, that adds the public teabot to a server. Added with a script rather than
// by replacing the theme's header template, so the theme updates without our copy falling behind.
(() => {
  const INVITE = "https://discord.com/oauth2/authorize?client_id=1570928156100264097&scope=bot+applications.commands&permissions=8";

  function add() {
    const header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".teabot-header-invite")) return;
    const link = document.createElement("a");
    link.className = "teabot-header-invite";
    link.href = INVITE;
    link.textContent = "Add Teabot";
    link.title = "Add Teabot to your Discord guild";
    const search = header.querySelector(".md-search") || header.querySelector("[for=__search]");
    header.insertBefore(link, search ? search : null);
  }

  if (window.document$) window.document$.subscribe(add);
  else document.addEventListener("DOMContentLoaded", add);
})();
