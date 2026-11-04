/*
 * Themes the page before it is drawn, so there is no flash of the wrong look. The app saves the resolved
 * variables of the last theme in "orion-appearance-cache" (see src/theme/apply.ts); this only replays them.
 * Without a cache (a first visit) it falls back to light or dark from the old setting or the device.
 */
(function () {
  try {
    var root = document.documentElement
    var cache = JSON.parse(localStorage.getItem('orion-appearance-cache') || 'null')
    var legacy = localStorage.getItem('orion-theme')
    var wantsDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    var dark
    if (cache) dark = cache.mode === 'dark' || (cache.mode === 'system' && wantsDark)
    else dark = legacy === 'dark' || (legacy !== 'light' && wantsDark)
    if (dark) root.classList.add('dark')
    root.style.colorScheme = dark ? 'dark' : 'light'
    var meta = document.querySelector('meta[name="theme-color"]')
    if (cache) {
      var set = dark ? cache.dark : cache.light
      for (var name in set.vars) root.style.setProperty(name, set.vars[name])
      for (var key in cache.attrs) root.setAttribute('data-' + key, cache.attrs[key])
      if (meta) meta.setAttribute('content', set.themeColor)
      if (cache.fontLink) {
        var link = document.createElement('link')
        link.id = 'orion-theme-font'
        link.rel = 'stylesheet'
        link.href = cache.fontLink
        document.head.appendChild(link)
      }
    } else if (meta) {
      meta.setAttribute('content', dark ? '#0a101b' : '#f3f5f9')
    }
  } catch {
    // a theme that cannot be read leaves the stylesheet's own default; the page must still start
  }
})()
