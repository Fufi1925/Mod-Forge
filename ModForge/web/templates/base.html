import { Link, useLocation } from "react-router-dom";
import { useState, useRef, useEffect } from "react";
import {
  Bot, Menu, X, Gauge, Activity, Home, Sparkles, Heart, ChevronDown,
  BookOpen, Crown, Zap, Shield, Ticket, Music, BarChart3, Command,
  MessageSquare, Lightbulb, Award, Calendar, Users, Headphones, FileText,
  Layout, Plug, Coins, Smile, Video, RefreshCw, HelpCircle, Code2,
  Briefcase, Mail, Server, Lock, Globe, Layers,
  Cpu, Cloud, TrendingUp, Bell, Wrench, ArrowUpRight
} from "lucide-react";

interface NavLink {
  to: string;
  label: string;
  desc?: string;
  icon?: any;
  badge?: string;
}

interface NavGroup {
  title: string;
  links: NavLink[];
}

interface MegaMenu {
  label: string;
  icon: any;
  cols: NavGroup[];
  cta?: { title: string; desc: string; to: string };
}

const megaMenus: MegaMenu[] = [
  {
    label: "Produkt",
    icon: Sparkles,
    cols: [
      {
        title: "Module",
        links: [
          { to: "/features", label: "Alle Features", desc: "Komplette Übersicht", icon: Layers },
          { to: "/commands", label: "100+ Commands", desc: "Slash + Prefix Commands", icon: Command },
          { to: "/economy", label: "Economy System", desc: "Coins, Shop & Gambling", icon: Coins },
          { to: "/ai", label: "AI Features", desc: "GPT-4 Integration", icon: Cpu, badge: "Neu" },
        ],
      },
      {
        title: "Tools",
        links: [
          { to: "/templates", label: "Server Templates", desc: "Vorgefertigte Setups", icon: Layout },
          { to: "/integrations", label: "Integrationen", desc: "Twitch, YouTube, GitHub", icon: Plug },
          { to: "/widgets", label: "Embed Widgets", desc: "Stats für deine Website", icon: Code2 },
          { to: "/emojis", label: "Emoji Pack", desc: "Custom Emojis Download", icon: Smile },
        ],
      },
      {
        title: "Module Details",
        links: [
          { to: "/docs/automod", label: "AutoMod 2.0", desc: "KI-Schutz", icon: Shield },
          { to: "/docs/tickets", label: "Tickets", desc: "Dropdown Panel", icon: Ticket },
          { to: "/docs/music", label: "Music Player", desc: "Lavalink Audio", icon: Music },
          { to: "/badges", label: "Badges", desc: "Achievement-System", icon: Award },
        ],
      },
    ],
    cta: {
      title: "Premium freischalten",
      desc: "24/7 Music & Custom Branding",
      to: "/premium"
    },
  },
];

const directLinks = [
  { to: "/pricing", label: "Pricing", icon: Crown, highlight: true },
  { to: "/status", label: "Status", icon: Activity },
  { to: "/dashboard", label: "Dashboard", icon: Gauge },
];

export default function Layout({
  children,
  scrolled
}: {
  children: React.ReactNode;
  scrolled: boolean;
}) {

  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  // NOTICE BANNER
  const [noticeClosed, setNoticeClosed] = useState(false);

  const navRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem("global-notice-closed");
    if (saved === "true") {
      setNoticeClosed(true);
    }
  }, []);

  const closeNotice = () => {
    setNoticeClosed(true);
    localStorage.setItem("global-notice-closed", "true");
  };

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenDropdown(null);
      }
    };

    document.addEventListener("click", onClick);

    return () => document.removeEventListener("click", onClick);
  }, []);

  return (
    <div className="min-h-screen bg-[#060816] text-white overflow-hidden">

      {/* GLOBAL NOTICE */}
      {!noticeClosed && (
        <div className="w-full bg-red-500/10 border-b border-red-500/20 text-sm">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <span>⚠️</span>

              <strong>Admin-Dashboard vorübergehend ausgefallen</strong>

              <span className="text-green-400">🟢 NEU:</span>

              <Link
                to="/live"
                className="underline text-cyan-300 hover:text-cyan-200 font-semibold"
              >
                /live – Echtzeit-Bot-Aktivität jetzt verfolgen
              </Link>
            </div>

            <button
              onClick={closeNotice}
              className="text-lg hover:text-red-300 transition"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* NAVBAR */}
      <header className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${scrolled ? "py-1.5" : "py-3"}`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6" ref={navRef}>

          <div className={`backdrop-blur-2xl bg-white/5 border border-white/10 rounded-2xl flex items-center justify-between px-4 sm:px-5 py-2.5 transition-all ${scrolled ? "shadow-2xl" : ""}`}>

            {/* LOGO */}
            <Link to="/" className="flex items-center gap-2.5 group shrink-0">
              <div className="relative">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-cyan-400 flex items-center justify-center">
                  <Shield className="w-5 h-5 text-white" />
                </div>

                <div className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-green-400 rounded-full border-2 border-[#0a0a14]" />
              </div>

              <div className="flex flex-col leading-tight">
                <span className="text-base font-black bg-gradient-to-r from-violet-400 to-cyan-300 bg-clip-text text-transparent">
                  ModForge
                </span>

                <span className="text-[8px] text-gray-500 tracking-widest uppercase -mt-0.5 hidden sm:block">
                  v3.0 · Live
                </span>
              </div>
            </Link>

            {/* DESKTOP NAV */}
            <nav className="hidden xl:flex items-center gap-0.5">

              <Link
                to="/"
                className={`px-3 py-2 rounded-xl text-[13px] font-medium transition-all flex items-center gap-1.5 ${
                  location.pathname === "/"
                    ? "text-white bg-white/5"
                    : "text-gray-300 hover:text-white hover:bg-white/5"
                }`}
              >
                <Home className="w-3.5 h-3.5" />
                Home
              </Link>

              {/* MEGA MENUS */}
              {megaMenus.map((menu) => {
                const Icon = menu.icon;
                const isOpen = openDropdown === menu.label;

                return (
                  <div key={menu.label} className="relative">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenDropdown(isOpen ? null : menu.label);
                      }}
                      className={`px-3 py-2 rounded-xl text-[13px] font-medium transition-all flex items-center gap-1.5 ${
                        isOpen
                          ? "text-white bg-white/10"
                          : "text-gray-300 hover:text-white hover:bg-white/5"
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />

                      {menu.label}

                      <ChevronDown className={`w-3 h-3 opacity-50 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                    </button>
                  </div>
                );
              })}

              {/* DIRECT LINKS */}
              {directLinks.map((link) => {
                const Icon = link.icon;
                const active = location.pathname === link.to;

                return (
                  <Link
                    key={link.to}
                    to={link.to}
                    className={`px-3 py-2 rounded-xl text-[13px] font-medium transition-all flex items-center gap-1.5 ${
                      link.highlight
                        ? "text-amber-300 hover:text-amber-200 hover:bg-amber-500/10"
                        : active
                          ? "text-white bg-white/5 border border-violet-500/30"
                          : "text-gray-300 hover:text-white hover:bg-white/5"
                    }`}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {link.label}
                  </Link>
                );
              })}
            </nav>

            {/* CTA */}
            <div className="flex items-center gap-2">

              <a
                href="/login"
                className="hidden sm:inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-violet-500 to-cyan-500 text-xs font-semibold hover:scale-[1.03] transition"
              >
                <Gauge className="w-3.5 h-3.5" />
                Dashboard ↗
              </a>

              <button
                className="xl:hidden w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center"
                onClick={() => setMobileOpen(!mobileOpen)}
              >
                {mobileOpen
                  ? <X className="w-4 h-4" />
                  : <Menu className="w-4 h-4" />
                }
              </button>
            </div>
          </div>

          {/* MEGA MENU PANEL */}
          {openDropdown && (
            <div className="hidden xl:block mt-2 backdrop-blur-2xl bg-[#0b1020]/95 rounded-2xl p-6 border border-white/10 shadow-2xl overflow-hidden">

              {megaMenus.filter(m => m.label === openDropdown).map((menu) => (
                <div key={menu.label} className="grid grid-cols-1 lg:grid-cols-4 gap-6">

                  {menu.cols.map((col, i) => (
                    <div key={i}>

                      <h4 className="text-[10px] uppercase tracking-widest text-gray-500 font-bold mb-3 px-2">
                        {col.title}
                      </h4>

                      <div className="space-y-1">

                        {col.links.map((link) => {
                          const Icon = link.icon;

                          return (
                            <Link
                              key={link.to}
                              to={link.to}
                              onClick={() => setOpenDropdown(null)}
                              className="flex items-start gap-3 p-2.5 rounded-xl hover:bg-white/5 transition"
                            >

                              {Icon && (
                                <div className="w-8 h-8 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
                                  <Icon className="w-4 h-4 text-violet-300" />
                                </div>
                              )}

                              <div className="min-w-0 flex-1">

                                <div className="flex items-center gap-1.5">

                                  <span className="text-sm font-semibold text-white">
                                    {link.label}
                                  </span>

                                  {link.badge && (
                                    <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-300">
                                      {link.badge}
                                    </span>
                                  )}
                                </div>

                                {link.desc && (
                                  <div className="text-[11px] text-gray-400 mt-0.5">
                                    {link.desc}
                                  </div>
                                )}
                              </div>
                            </Link>
                          );
                        })}
                      </div>
                    </div>
                  ))}

                  {menu.cta && (
                    <div className="lg:col-span-4 mt-2 pt-4 border-t border-white/5">

                      <Link
                        to={menu.cta.to}
                        className="flex items-center justify-between p-4 rounded-xl bg-gradient-to-r from-violet-500/15 to-cyan-500/15 border border-violet-500/20 hover:border-violet-500/40 transition"
                      >
                        <div>
                          <div className="font-bold text-white text-sm">
                            {menu.cta.title}
                          </div>

                          <div className="text-xs text-gray-400 mt-0.5">
                            {menu.cta.desc}
                          </div>
                        </div>

                        <ArrowUpRight className="w-5 h-5 text-violet-300" />
                      </Link>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* MOBILE MENU */}
          {mobileOpen && (
            <div className="xl:hidden mt-2 backdrop-blur-2xl bg-[#0b1020]/95 p-3 max-h-[80vh] overflow-y-auto rounded-2xl border border-white/10">

              <Link
                to="/"
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm text-gray-300 hover:bg-white/5 hover:text-white"
              >
                <Home className="w-4 h-4 text-violet-400" />
                Home
              </Link>

              {megaMenus.map((menu) => (
                <details key={menu.label} className="group">

                  <summary className="flex items-center justify-between px-4 py-2.5 rounded-xl text-sm font-medium text-gray-300 hover:bg-white/5 cursor-pointer list-none">

                    <span className="flex items-center gap-2">
                      <menu.icon className="w-4 h-4 text-violet-400" />
                      {menu.label}
                    </span>

                    <ChevronDown className="w-3.5 h-3.5 group-open:rotate-180 transition" />
                  </summary>

                  <div className="ml-6 mt-1 mb-2 space-y-0.5">

                    {menu.cols.flatMap(c => c.links).map((link) => (
                      <Link
                        key={link.to}
                        to={link.to}
                        onClick={() => setMobileOpen(false)}
                        className="block px-3 py-2 rounded-lg text-[13px] text-gray-400 hover:text-white hover:bg-white/5"
                      >
                        {link.label}
                      </Link>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      </header>

      {/* PAGE CONTENT */}
      <main className="pt-28 relative z-10">
        {children}
      </main>

      {/* FOOTER */}
      <footer className="border-t border-white/10 mt-20">

        <div className="max-w-7xl mx-auto px-6 py-14 grid grid-cols-1 md:grid-cols-4 gap-10">

          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-cyan-400 flex items-center justify-center">
                <Shield className="w-5 h-5 text-white" />
              </div>

              <span className="font-black text-lg bg-gradient-to-r from-violet-400 to-cyan-300 bg-clip-text text-transparent">
                ModForge
              </span>
            </div>

            <p className="text-sm text-gray-400">
              Security & AutoMod Bot für Discord.
            </p>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Links</h4>

            <div className="space-y-2 text-sm text-gray-400">
              <Link to="/status" className="block hover:text-white">Status</Link>
              <Link to="/changelog" className="block hover:text-white">Changelog</Link>
              <Link to="/live" className="block hover:text-white">Live Aktivität</Link>
              <Link to="/dashboard" className="block hover:text-white">Dashboard</Link>
            </div>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Rechtliches</h4>

            <div className="space-y-2 text-sm text-gray-400">
              <Link to="/terms" className="block hover:text-white">Terms</Link>
              <Link to="/privacy" className="block hover:text-white">Privacy</Link>
              <Link to="/imprint" className="block hover:text-white">Impressum</Link>
            </div>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Community</h4>

            <div className="space-y-2 text-sm text-gray-400">
              <a
                href="https://discord.gg/gwryX3dbkt"
                target="_blank"
                className="block hover:text-white"
              >
                Support Server
              </a>

              <Link to="/admin/login" className="block hover:text-white">
                Admin Panel
              </Link>
            </div>
          </div>
        </div>

        <div className="border-t border-white/5 py-5 text-center text-xs text-gray-500">
          © 2026 ModForge · Powered by BotForge · v3.0.0
        </div>
      </footer>
    </div>
  );
}
