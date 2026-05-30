(() => {
    const html = document.documentElement;
    const storageKey = "__THEME_CONFIG__";
    const attributes = {
        "data-skin": "skin",
        "data-theme": "theme",
        "data-menu-color": "sidenavColor",
        "data-sidenav-size": "sidenavSize",
        "data-topbar-color": "topbarColor",
        "data-layout-position": "position",
        "data-layout-width": "width",
        dir: "dir",
        "data-sidenav-user": "sidenavUser",
    };
    const defaults = {
        dir: "ltr",
        skin: "default",
        theme: "light",
        width: "fluid",
        position: "fixed",
        orientation: "vertical",
        sidenavSize: "default",
        sidenavUser: false,
        topbarColor: "light",
        sidenavColor: "dark",
    };

    const readStoredConfig = () => {
        try {
            return JSON.parse(sessionStorage.getItem(storageKey) || "{}");
        } catch {
            return {};
        }
    };
    const readHtmlConfig = () => {
        const config = {};
        Object.entries(attributes).forEach(([attribute, key]) => {
            const value = html.getAttribute(attribute);
            if (value !== null) {
                config[key] = key === "sidenavUser" ? value === "true" : value;
            }
        });
        return config;
    };
    const readQueryConfig = () => {
        const params = new URLSearchParams(window.location.search);
        const config = {};
        Object.values(attributes).forEach((key) => {
            const value = params.get(key);
            if (value) {
                config[key] = key === "sidenavUser" ? value === "true" : value;
            }
        });
        return config;
    };

    window.skinPresets = {
        neo: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "gray" },
        zen: { theme: "light", sidenavUser: false, topbarColor: "gray", sidenavColor: "dark" },
        flat: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "light" },
        luxe: { theme: "light", sidenavUser: false, topbarColor: "dark", sidenavColor: "light" },
        mono: { theme: "light", sidenavUser: false, topbarColor: "dark", sidenavColor: "light" },
        neon: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "light" },
        nova: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        saas: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        soft: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "gradient" },
        orbit: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        pixel: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        prism: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "light" },
        retro: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        vivid: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        xenon: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "gradient" },
        aurora: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        galaxy: { theme: "dark" },
        matrix: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        modern: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        silver: { theme: "light", sidenavUser: false, topbarColor: "dark", sidenavColor: "light" },
        crystal: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        default: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        elegant: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "dark" },
        minimal: { theme: "light", sidenavUser: false, topbarColor: "gray", sidenavColor: "gray" },
        material: { theme: "light", sidenavUser: false, topbarColor: "light", sidenavColor: "gray" },
    };

    const storedConfig = readStoredConfig();
    const htmlConfig = readHtmlConfig();
    const queryConfig = readQueryConfig();
    const skinName = queryConfig.skin || htmlConfig.skin || storedConfig.skin || defaults.skin;
    const skinConfig = window.skinPresets[skinName] || {};
    const config = {
        ...defaults,
        ...skinConfig,
        ...storedConfig,
        ...htmlConfig,
        ...queryConfig,
        skin: skinName,
    };

    if (["on-hover", "on-hover-active"].includes(config.sidenavSize)) {
        config.sidenavSize = "default";
    }
    config.sidenavUser = false;

    window.defaultConfig = structuredClone(config);
    window.config = config;

    const setAttribute = (attribute, value) => {
        if (value) {
            html.setAttribute(attribute, value);
        }
    };
    const resolvedTheme = config.theme === "system"
        ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : config.theme;

    setAttribute("data-skin", config.skin);
    setAttribute("data-theme", resolvedTheme);
    setAttribute("data-menu-color", config.sidenavColor);
    setAttribute("data-topbar-color", config.topbarColor);
    setAttribute("data-layout-width", config.width);
    setAttribute("data-layout-position", config.position);
    setAttribute("dir", config.dir);

    let sidenavSize = config.sidenavSize;
    if (window.innerWidth <= 767) {
        sidenavSize = "offcanvas";
    } else if (window.innerWidth <= 1140 && sidenavSize !== "offcanvas") {
        sidenavSize = "condensed";
    }
    setAttribute("data-sidenav-size", sidenavSize);

    if (config.sidenavUser) {
        html.setAttribute("data-sidenav-user", "true");
    } else {
        html.removeAttribute("data-sidenav-user");
    }
})();
