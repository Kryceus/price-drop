import { useState } from "react";

export default function NavBar({
  appUnlocked,
  currentPage,
  currentUser,
  watchlistCount,
  dropCount,
  appMode,
  onShowPage,
  onEnterGuest,
  onLogout,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  function handleNavigate(page) {
    onShowPage(page);
    setMenuOpen(false);
  }

  function handleExit() {
    if (appMode === "demo") {
      onEnterGuest();
    } else {
      onLogout();
    }
    setMenuOpen(false);
  }

  return (
    <nav>
      <div className="nav-brand">
        <span className="nav-dot" />
        PriceWatch
      </div>
      <div className="nav-right">
        <div className="nav-tabs nav-tabs-desktop">
          {appUnlocked ? (
            <>
              <button
                className={`nav-tab ${currentPage === "check" ? "active" : ""}`}
                type="button"
                onClick={() => handleNavigate("check")}
              >
                Price Check
              </button>
              <button
                className={`nav-tab ${currentPage === "dashboard" ? "active" : ""}`}
                type="button"
                onClick={() => handleNavigate("dashboard")}
              >
                Dashboard
                {watchlistCount ? (
                  <span className={`badge ${dropCount ? "drop" : ""}`}>
                    {dropCount || watchlistCount}
                  </span>
                ) : null}
              </button>
              {currentUser ? (
                <button
                  className={`nav-tab ${currentPage === "account" ? "active" : ""}`}
                  type="button"
                  onClick={() => handleNavigate("account")}
                >
                  {currentUser.username}
                </button>
              ) : appMode === "demo" ? (
                <button
                  className={`nav-tab ${currentPage === "account" ? "active" : ""}`}
                  type="button"
                  onClick={() => handleNavigate("account")}
                >
                  Account
                </button>
              ) : null}
            </>
          ) : null}
        </div>

        {appMode === "demo" ? <span className="mode-chip demo">Demo</span> : null}
        {appMode === "demo" ? (
          <button className="btn-secondary" type="button" onClick={onEnterGuest}>
            Leave Demo
          </button>
        ) : null}
        {appMode === "account" && currentUser ? (
          <button className="btn-secondary" type="button" onClick={onLogout}>
            Log Out
          </button>
        ) : null}

        {appUnlocked ? (
          <>
            <button
              className={`menu-toggle ${menuOpen ? "active" : ""}`}
              type="button"
              aria-label="Open navigation menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((current) => !current)}
            >
              <span />
              <span />
              <span />
            </button>
            {menuOpen ? (
              <button
                className="menu-scrim"
                type="button"
                aria-label="Close navigation menu"
                onClick={() => setMenuOpen(false)}
              />
            ) : null}
            <aside className={`mobile-drawer ${menuOpen ? "open" : ""}`}>
              <div className="drawer-head">
                <div>
                  <div className="drawer-kicker">Menu</div>
                  <div className="drawer-title">Navigate</div>
                  <div className="drawer-subtitle">
                    {currentUser ? `Signed in as @${currentUser.username}` : "Demo mode"}
                  </div>
                </div>
                <button
                  className="drawer-close"
                  type="button"
                  aria-label="Close navigation menu"
                  onClick={() => setMenuOpen(false)}
                >
                  x
                </button>
              </div>
              <div className="drawer-links">
                <button
                  className={`drawer-link ${currentPage === "check" ? "active" : ""}`}
                  type="button"
                  onClick={() => handleNavigate("check")}
                >
                  <span className="drawer-link-title">Price Check</span>
                  <span className="drawer-link-copy">Search a product and save it to your watchlist.</span>
                </button>
                <button
                  className={`drawer-link ${currentPage === "dashboard" ? "active" : ""}`}
                  type="button"
                  onClick={() => handleNavigate("dashboard")}
                >
                  <span className="drawer-link-title">Dashboard</span>
                  <span className="drawer-link-copy">
                    View tracked products{watchlistCount ? ` and ${watchlistCount} saved item${watchlistCount === 1 ? "" : "s"}` : ""}.
                  </span>
                </button>
                <button
                  className={`drawer-link ${currentPage === "account" ? "active" : ""}`}
                  type="button"
                  onClick={() => handleNavigate("account")}
                >
                  <span className="drawer-link-title">Account</span>
                  <span className="drawer-link-copy">User details, appearance, and app settings.</span>
                </button>
              </div>
              <div className="drawer-footer">
                <button className="drawer-exit" type="button" onClick={handleExit}>
                  {appMode === "demo" ? "Leave Demo" : "Log Out"}
                </button>
              </div>
            </aside>
          </>
        ) : null}
      </div>
    </nav>
  );
}
