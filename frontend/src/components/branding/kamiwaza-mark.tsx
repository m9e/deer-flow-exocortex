import { cn } from "@/lib/utils";
import { withAppBasePath } from "@/core/config";

export function KamiwazaMark({
  className,
  size = 26,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <img
      src={withAppBasePath("/kamiwaza-mark.png")}
      alt="Kamiwaza"
      className={cn(
        "inline-block shrink-0 object-contain shadow-[var(--kz-shadow-primary)]",
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}

export function KamiwazaWordmark({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2.5", className)}>
      {collapsed ? (
        <KamiwazaMark />
      ) : (
        <>
          <KamiwazaMark size={28} className="shadow-none" />
          <div
            aria-label="Kamiwaza Flow"
            className="flex min-w-0 flex-col items-start font-black leading-[0.8] text-[var(--kz-text)] uppercase"
          >
            <span className="text-[16px]">KAMI</span>
            <span className="text-[16px]">WAZA</span>
            <span className="mt-[3px] text-[9px] leading-none text-[var(--kz-primary)]">
              FLOW
            </span>
          </div>
        </>
      )}
    </div>
  );
}
