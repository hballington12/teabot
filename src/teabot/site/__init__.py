"""The instance's own website (D53): its home page, its plugin browser, and its operator's privacy policy and terms.

A server's admins sign in with Discord, choose a server, and turn its plugins on and off or change their settings
in place, with no commands. Every instance serves it at its public address; the official Teabot is one instance.

- `app`: the routes, and every change made as the signed-in member through the registry.
- `info`: what the site says of each installed plugin.
- `layout` and `pages`: the HTML, with everything a member, a plugin or an operator wrote escaped.
- `oauth` and `sessions`: signing in with Discord, and the sign-ins kept.
- `static/`: the stylesheet, the script that saves without reloading, and the logo.
"""
