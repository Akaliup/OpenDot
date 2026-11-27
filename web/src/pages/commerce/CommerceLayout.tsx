import { Suspense } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  CommerceConnectionProvider,
  CommerceOfflineBanner,
} from './connection';

const links = [
  { to: '/commerce', label: '概览', end: true },
  { to: '/commerce/approvals', label: '审批', end: false },
  { to: '/commerce/evals', label: '评测', end: false },
];

export function CommerceLayout() {
  return (
    <CommerceConnectionProvider>
      <div className="min-h-full px-4 py-5 sm:px-6 lg:px-8 lg:py-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-6">
          <header>
            <h1 className="product-page-title">经营</h1>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              数字来自 CommerceOps
              计算引擎。预算、采购和竞品动作先成为草案，批准后才写入。
            </p>
          </header>
          <nav
            aria-label="经营页面"
            className="flex gap-1 border-b border-border"
          >
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  `inline-flex min-h-11 items-center border-b-2 px-3 text-sm ${
                    isActive
                      ? 'border-primary text-foreground'
                      : 'border-transparent text-muted-foreground'
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <CommerceOfflineBanner />
          <Suspense
            fallback={
              <p className="text-sm text-muted-foreground" role="status">
                正在加载经营页面…
              </p>
            }
          >
            <Outlet />
          </Suspense>
        </div>
      </div>
    </CommerceConnectionProvider>
  );
}
