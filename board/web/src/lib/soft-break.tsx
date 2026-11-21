import type { ReactNode } from "react";

function softBreak(value: string): ReactNode[] {
  return value.split(/([ \-_/])/).map((part, index) =>
    part === " " || part === "-" || part === "_" || part === "/" ? (
      <span key={index}>
        {part}
        <wbr />
      </span>
    ) : (
      <span key={index}>{part}</span>
    ),
  );
}

export { softBreak };
