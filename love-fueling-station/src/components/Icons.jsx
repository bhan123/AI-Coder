const paths = {
  back: <path d="m15 18-6-6 6-6" />,
  home: <><path d="m3 10 9-7 9 7" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /></>,
  book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>,
  pencil: <><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  wrench: <><path d="M14.7 6.3a4 4 0 0 0-5-5L7.2 3.8l3 3 2.5-2.5a4 4 0 0 0 2 5L6 18l-3 3 3 3 3-3 8.7-8.7a4 4 0 0 0 5-5l-2.5 2.5-3-3Z" /></>,
  camera: <><path d="M14.5 4 16 7h4a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h4l1.5-3Z" /><circle cx="12" cy="13" r="3" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  close: <><path d="m18 6-12 12" /><path d="m6 6 12 12" /></>,
  adjust: <><path d="M4 21v-7" /><path d="M4 10V3" /><path d="M12 21v-9" /><path d="M12 8V3" /><path d="M20 21v-5" /><path d="M20 12V3" /><path d="M1 14h6" /><path d="M9 8h6" /><path d="M17 16h6" /></>,
  leaf: <><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 18 2 18 2c1 6-1 13-7 15" /><path d="M2 21c0-3 1.85-5.36 5.08-6.94C9.23 13 12 12 16 12" /></>,
};

export function Icon({ name, size = 22, strokeWidth = 1.8, className = '' }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={strokeWidth}
    >
      {paths[name]}
    </svg>
  );
}

export function SparkMark({ size = 32 }) {
  return (
    <svg aria-hidden="true" className="spark-mark" height={size} viewBox="0 0 36 36" width={size}>
      <path d="M18 2v8M18 26v8M2 18h8M26 18h8M6.7 6.7l5.6 5.6M23.7 23.7l5.6 5.6M29.3 6.7l-5.6 5.6M12.3 23.7l-5.6 5.6" />
      <circle cx="18" cy="18" r="4.5" />
    </svg>
  );
}
