import { cn } from "../../lib/utils";
import { CheckCircle } from "lucide-react";

interface StudentAvatarProps {
  name?: string;
  isVerified?: boolean;
  className?: string;
}

export function StudentAvatar({ name, isVerified, className }: StudentAvatarProps) {
  const getInitials = (name?: string) => {
    if (!name) return "W";
    const parts = name.trim().split(/\s+/);
    if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  };

  return (
    <div className={cn("relative inline-flex", className)}>
      <div
        className="flex h-24 w-24 items-center justify-center rounded-full bg-slate-100 text-3xl font-bold text-slate-700 shadow-sm border border-slate-200"
        aria-label={`Avatar for ${name || "User"}`}
      >
        {getInitials(name)}
      </div>
      {isVerified && (
        <div className="absolute bottom-0 right-1 rounded-full bg-white p-[2px] shadow-sm">
          <CheckCircle className="h-6 w-6 text-emerald-500 fill-white" />
        </div>
      )}
    </div>
  );
}
