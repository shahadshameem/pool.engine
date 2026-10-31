import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { useAuth } from "../hooks/useAuth"
import { useBackNavigation } from "../hooks/useBackNavigation"
import { useToast } from "../components/feedback/ToastContext"
import { userService } from "../services/user/userService"
import { SmsMfaCard } from "../components/security/SmsMfaCard"
import { cn } from "../lib/utils"

export function AccountInfoPage() {
  const navigate = useNavigate()
  const { goBack, registerDirtyGuard } = useBackNavigation()
  const { user, profile } = useAuth()
  const { showToast } = useToast()
  const [name, setName] = useState("")
  const [gender, setGender] = useState<"male" | "female" | "">("")
  const [phone, setPhone] = useState("")
  const [isSaving, setIsSaving] = useState(false)

  // Dirty form guard for profile edits
  useEffect(() => {
    const isDirty = () => {
      const origName = profile?.name || user?.displayName || ""
      const origPhone = (profile?.phone && profile.phone !== "0000000000" ? profile.phone : user?.phoneNumber || "").replace(/\D/g, "").slice(-10)
      return name.trim() !== origName.trim() || phone.trim() !== origPhone.trim()
    }
    const unregister = registerDirtyGuard("edit-profile-form", isDirty, "Discard unsaved profile changes?")
    return unregister
  }, [name, phone, profile, user, registerDirtyGuard])

  useEffect(() => {
    if (!user) {
      navigate("/login", { replace: true })
    } else if (profile) {
      const resolvedName = (profile.name && profile.name !== "Student" && profile.name !== "User")
        ? profile.name
        : (user?.displayName || (user?.email ? user.email.split("@")[0] : "") || profile.name || "")
      setName(resolvedName)
      setGender((profile.gender as "male" | "female") || "")
      const rawPhone = (profile.phone && profile.phone !== "0000000000" ? profile.phone : user?.phoneNumber || "")
      setPhone(rawPhone.replace(/\D/g, "").slice(-10))
    } else if (user) {
      setName(user.displayName || user.email?.split("@")[0] || "")
      if (user.phoneNumber) {
        setPhone(user.phoneNumber.replace(/\D/g, "").slice(-10))
      }
    }
  }, [user, profile, navigate])

  const isGenderLocked = Boolean(profile?.gender && (profile.gender === "male" || profile.gender === "female"))

  const handleSaveProfile = async () => {
    if (!user) return
    const trimmed = name.trim()
    if (!trimmed) {
      showToast("Name cannot be empty", "error")
      return
    }
    if (!isGenderLocked && !gender) {
      showToast("Please select your gender", "error")
      return
    }
    const cleanPhone = phone.replace(/\D/g, "")
    if (!cleanPhone) {
      showToast("Phone number is required for ride coordination", "error")
      return
    }
    if (cleanPhone.length < 10) {
      showToast("Please enter a valid 10-digit mobile number", "error")
      return
    }

    setIsSaving(true)
    try {
      const updateData: Record<string, any> = {
        name: trimmed,
        phone: cleanPhone.slice(-10),
      }
      if (!isGenderLocked && gender) {
        updateData.gender = gender
      }

      await userService.updateUserProfile(user.uid, updateData)
      showToast("Profile updated successfully!", "success")
    } catch (err: any) {
      console.error("Failed to update profile:", err)
      showToast(err?.message || "Failed to update profile", "error")
    } finally {
      setIsSaving(false)
    }
  }

  const displayName = profile?.name || name || user?.displayName || "User"
  const initial = displayName.trim().charAt(0).toUpperCase()

  return (
    <MobileShell hideBottomNav className="flex flex-col space-y-6">
      {/* Header */}
      <div className="flex items-center space-x-2">
        <button
          onClick={goBack}
          className="p-2 -ml-2 rounded-full hover:bg-muted transition-colors cursor-pointer"
          aria-label="Back"
        >
          <MaterialIcon name="arrow_back" className="text-[24px] text-foreground" />
        </button>
        <h1 className="text-edex-heading text-foreground font-bold">Edit Profile</h1>
      </div>

      {/* Avatar Container */}
      <div className="flex flex-col items-center justify-center space-y-3 py-2">
        <div className="h-24 w-24 rounded-full bg-foreground text-background border-2 border-foreground flex items-center justify-center font-bold text-[36px] shadow-sm">
          {initial}
        </div>
      </div>

      {/* Form Fields */}
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Full Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full h-[54px] bg-card border border-border/60 rounded-2xl px-4 text-[16px] text-foreground font-medium focus:outline-none focus:border-foreground"
          />
        </div>

        {/* Gender Selection */}
        <div className="space-y-1.5">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Gender
          </label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              disabled={isGenderLocked}
              onClick={() => !isGenderLocked && setGender("male")}
              className={cn(
                "h-[54px] rounded-2xl border font-bold text-[15px] flex items-center justify-center transition-all",
                isGenderLocked ? "cursor-not-allowed opacity-90" : "cursor-pointer",
                gender === "male"
                  ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                  : "bg-card border-border/60 text-foreground hover:bg-muted font-semibold"
              )}
            >
              Male
            </button>
            <button
              type="button"
              disabled={isGenderLocked}
              onClick={() => !isGenderLocked && setGender("female")}
              className={cn(
                "h-[54px] rounded-2xl border font-bold text-[15px] flex items-center justify-center transition-all",
                isGenderLocked ? "cursor-not-allowed opacity-90" : "cursor-pointer",
                gender === "female"
                  ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                  : "bg-card border-border/60 text-foreground hover:bg-muted font-semibold"
              )}
            >
              Female
            </button>
          </div>
          {isGenderLocked && (
            <p className="text-[12px] text-muted-foreground flex items-center space-x-1 pt-0.5 px-0.5">
              <MaterialIcon name="lock" className="text-[14px]" />
              <span>Gender is locked once applied and cannot be changed.</span>
            </p>
          )}
        </div>

        {/* Phone Number Field */}
        <div className="space-y-1.5">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Phone Number (WhatsApp) <span className="text-destructive">*</span>
          </label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-muted-foreground select-none">
              +91
            </span>
            <input
              type="tel"
              maxLength={10}
              placeholder="9876543210"
              value={phone}
              onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
              className="w-full h-[54px] bg-card border border-border/60 rounded-2xl pl-13 pr-4 text-[16px] text-foreground font-medium focus:outline-none focus:border-foreground"
            />
          </div>
          <p className="text-[12px] text-muted-foreground">
            Used by confirmed co-riders to contact you for rides.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            College
          </label>
          <input
            type="text"
            value={profile?.college || "College of Engineering Trivandrum (CET)"}
            disabled
            className="w-full h-[54px] bg-muted border border-border/40 rounded-2xl px-4 text-[16px] text-muted-foreground font-medium"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Email
          </label>
          <input
            type="email"
            value={profile?.email || user?.email || ""}
            disabled
            className="w-full h-[54px] bg-muted border border-border/40 rounded-2xl px-4 text-[16px] text-muted-foreground font-medium"
          />
        </div>

        <Button
          variant="primary"
          size="lg"
          className="w-full mt-4"
          disabled={isSaving}
          onClick={handleSaveProfile}
        >
          {isSaving ? "Saving..." : "Save Changes"}
        </Button>

        {/* SMS Multi-Factor Authentication Card */}
        <div className="pt-6 space-y-2">
          <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
            Account Security
          </label>
          <SmsMfaCard />
        </div>
      </div>
    </MobileShell>
  )
}
