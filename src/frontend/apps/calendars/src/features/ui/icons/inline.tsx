/**
 * Inline SVG fallbacks for Material Icons glyphs that have no direct
 * ``@gouvfr-lasuite/ui-kit/icons`` equivalent at the time of migration.
 *
 * Each component matches the props shape of the ui-kit icons
 * (``className``, ``style``, ``aria-*``) so call sites can mix
 * inline and ui-kit icons freely. Path data is the standard 24x24
 * Material-style geometry, simplified where it doesn't hurt
 * recognisability.
 */

import type { CSSProperties, SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & {
  className?: string;
  style?: CSSProperties;
};

const Svg = ({
  children,
  className,
  style,
  ...rest
}: Props & { children: React.ReactNode }) => (
  <svg
    className={className}
    style={style}
    viewBox="0 0 24 24"
    width="1em"
    height="1em"
    fill="currentColor"
    aria-hidden={rest["aria-label"] ? undefined : true}
    {...rest}
  >
    {children}
  </svg>
);

export const AttachFileSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M16.5 6v11.5a4.5 4.5 0 1 1-9 0V5a3 3 0 0 1 6 0v10.5a1.5 1.5 0 0 1-3 0V6H10v9.5a2.5 2.5 0 0 0 5 0V5a4 4 0 0 0-8 0v12.5a5.5 5.5 0 0 0 11 0V6h-1.5z" />
  </Svg>
);

export const EventAvailableSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M19 3h-1V1h-2v2H8V1H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V9h14v10zM7.91 13.41 9.32 12 11 13.68 14.85 9.83l1.41 1.41-5.26 5.26z" />
  </Svg>
);

export const EventBusySvg = (props: Props) => (
  <Svg {...props}>
    <path d="M19 3h-1V1h-2v2H8V1H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V9h14v10zM9.31 17 12 14.31 14.69 17l1.42-1.41L13.41 12.9l2.7-2.69-1.42-1.41L12 11.49l-2.69-2.69-1.42 1.41 2.7 2.69-2.7 2.69z" />
  </Svg>
);

export const GroupSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M12 12.75c-2.34 0-7 1.17-7 3.5V18h14v-1.75c0-2.33-4.66-3.5-7-3.5zM7 9.5C7 11.43 8.57 13 10.5 13S14 11.43 14 9.5 12.43 6 10.5 6 7 7.57 7 9.5zM17.5 13c-.49 0-.99.07-1.51.21 1.06.75 1.51 1.83 1.51 3.04V18h4v-1.75c0-2.33-4-3.25-4-3.25zM17 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />
  </Svg>
);

export const NotesSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M3 18h12v-2H3v2zM3 6v2h18V6H3zm0 7h18v-2H3v2z" />
  </Svg>
);

export const PersonAddSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
  </Svg>
);

export const RepeatSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z" />
  </Svg>
);

export const ScienceSvg = (props: Props) => (
  <Svg {...props}>
    <path d="M19.8 18.4 14 10.67V6.5l1.35-1.69A1 1 0 0 0 14.57 3H9.43a1 1 0 0 0-.78 1.62L10 6.5v4.17L4.2 18.4A2 2 0 0 0 5.8 21.5h12.4a2 2 0 0 0 1.6-3.1zM11 11.5V6h2v5.5l3.4 4.5H7.6L11 11.5z" />
  </Svg>
);
