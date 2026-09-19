import { cn } from "@/lib/utils";

type LogoProps = {
  className?: string;
};
export default function Logo({ className }: LogoProps) {
  return (
    <img
      src="/assets/favicon-D-AQzSk_.svg"
      alt="Algerie Telecom"
      className={cn("h-full w-full", className)}
    />
  );
}