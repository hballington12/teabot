# First-party plugins

- Each plugin is its own package in a subdirectory and a member of the uv workspace (D42).
- `announcements/` arrives in WP2.9, with `devtools/` for development only.
- Plugins import only from `teapot.sdk` (D45), and keep their tests in their own `tests/`.
