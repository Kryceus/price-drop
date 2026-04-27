import { Home, LayoutGrid, User } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";

const tabs = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { to: "/account", label: "Account", icon: User },
];

export function BottomTabBar() {
  const { pathname } = useLocation();
  // Hide on auth/install full-screen pages if needed
  if (pathname.startsWith("/install")) return null;
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-elevated/95 backdrop-blur-md safe-bottom"
    >
      <ul className="mx-auto flex max-w-xl items-stretch justify-around px-2 pt-1.5">
        {tabs.map(({ to, label, icon: Icon, end }) => (
          <li key={to} className="flex-1">
            <NavLink
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex flex-col items-center gap-0.5 rounded-md px-2 py-2 text-[11px] font-medium transition-colors",
                  isActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "flex h-9 w-12 items-center justify-center rounded-full transition-colors",
                      isActive && "bg-primary-soft",
                    )}
                  >
                    <Icon className="h-5 w-5" strokeWidth={isActive ? 2.4 : 2} />
                  </span>
                  <span>{label}</span>
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
