import type { AnchorHTMLAttributes, ReactNode } from "react";

import { hrefTo, isActivePath, useRouteLocation } from "@/lib/router";

type AnchorProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

/** A link to another screen of the console. */
export function Link({ to, ...props }: { to: string } & AnchorProps) {
  return <a href={hrefTo(to)} {...props} />;
}

/** A navigation link that knows whether its screen is the one being shown. */
export function NavLink({
  to,
  end = false,
  className,
  children,
}: {
  to: string;
  end?: boolean;
  className: (active: boolean) => string;
  children: ReactNode;
}) {
  const { path } = useRouteLocation();
  const active = isActivePath(path, to, end);
  return (
    <a href={hrefTo(to)} aria-current={active ? "page" : undefined} className={className(active)}>
      {children}
    </a>
  );
}
