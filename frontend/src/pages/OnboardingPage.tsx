import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { MobileShell } from "../components/layout/MobileShell"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { MaterialIcon } from "../components/common/MaterialIcon"
import { ThemedSelect } from "../components/common/ThemedSelect"
import { useToast } from "../components/feedback/ToastContext"
import { useAuth } from "../hooks/useAuth"
import { doc, getDoc } from "firebase/firestore"
import { db } from "../config/firebase"
import { userService } from "../services/user/userService"
import { collegeService, type College, DEFAULT_COLLEGES } from "../services/college/collegeService"
import { CET_COLLEGE_NAME, CET_DEPARTMENT_OPTIONS, getYearOptionsForDepartment } from "../config/cetOptions"
import { cn } from "../lib/utils"

export function OnboardingPage() {
  const navigate = useNavigate()
  const { user, loading: authLoading } = useAuth()
  const { showToast } = useToast()

  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [profileExists, setProfileExists] = useState(false)
  const [colleges, setColleges] = useState<College[]>([])

  const [formData, setFormData] = useState({
    name: "",
    college: CET_COLLEGE_NAME,
    department: "",
    year: "",
    gender: "" as "male" | "female" | "",
    phone: "",
    homeLocation: "",
  })

  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!authLoading && !user) {
      navigate("/login", { replace: true })
      return
    }

    let cancelled = false

    async function loadProfileAndColleges() {
      if (!user) return

      try {
        // Fetch active colleges
        const activeColleges = await collegeService.getColleges(true)
        if (!cancelled) setColleges(activeColleges)

        // Try auto-detecting college by user's email domain
        const detectedCollege = await collegeService.detectCollegeByEmail(user.email || "")

        const docRef = doc(db, "users", user.uid)
        const docSnap = await getDoc(docRef)

        if (cancelled) return

        if (docSnap.exists()) {
          setProfileExists(true)
          const data = docSnap.data()
          const rawPhone = (data.phone && data.phone !== "0000000000" ? data.phone : user.phoneNumber || "")
          const phoneDigits = rawPhone.replace(/\D/g, "").slice(-10)
          const resolvedName = (data.name && data.name !== "Student" && data.name !== "User")
            ? data.name
            : (user.displayName || (user.email ? user.email.split("@")[0] : "") || "")

          setFormData({
            name: resolvedName,
            college: data.college || (detectedCollege ? detectedCollege.name : CET_COLLEGE_NAME),
            department: data.department || "",
            year: data.year || "",
            gender: (data.gender as "male" | "female") || "",
            phone: phoneDigits,
            homeLocation: data.homeLocation || "",
          })
        } else {
          const initialName = user.displayName || (user.email ? user.email.split("@")[0] : "") || ""
          const phoneDigits = (user.phoneNumber || "").replace(/\D/g, "").slice(-10)
          setFormData(prev => ({
            ...prev,
            name: initialName,
            phone: phoneDigits,
            college: detectedCollege ? detectedCollege.name : CET_COLLEGE_NAME
          }))
        }
      } catch (error) {
        if (cancelled) return
        console.error("Error loading profile or colleges:", error)
        showToast("Could not load profile data.", "error")
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    if (user) {
      loadProfileAndColleges()
    }

    return () => { cancelled = true }
  }, [user, authLoading, navigate])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    const val = name === "phone" ? value.replace(/\D/g, "").slice(0, 10) : value
    setFormData(prev => ({ ...prev, [name]: val }))
    if (errors[name]) {
      setErrors(prev => ({ ...prev, [name]: "" }))
    }
  }

  const handleDepartmentChange = (val: string) => {
    const isArch = val === "ARCH" || val.toLowerCase().includes("arch")
    setFormData(prev => {
      let updatedYear = prev.year
      if (!isArch && prev.year === "5th Year") {
        updatedYear = "4th Year"
      }
      return { ...prev, department: val, year: updatedYear }
    })
    if (errors.department) {
      setErrors(prev => ({ ...prev, department: "" }))
    }
  }

  const handleYearChange = (val: string) => {
    setFormData(prev => ({ ...prev, year: val }))
    if (errors.year) {
      setErrors(prev => ({ ...prev, year: "" }))
    }
  }

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!formData.name.trim()) newErrors.name = "Full name is required"
    if (!formData.gender) newErrors.gender = "Please select your gender"
    if (!formData.department) newErrors.department = "Please select your department / branch"
    if (!formData.year) newErrors.year = "Please select your year of study"

    const cleanPhone = formData.phone.replace(/\D/g, "")
    if (!cleanPhone) {
      newErrors.phone = "Phone number is required for ride coordination"
    } else if (cleanPhone.length < 10) {
      newErrors.phone = "Please enter a valid 10-digit mobile number"
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validate()) return
    if (!user) return

    setIsSaving(true)

    try {
      const cleanPhone = formData.phone.trim().replace(/\D/g, "")
      const formattedPhone = cleanPhone.length === 10 ? cleanPhone : cleanPhone.slice(-10)
      const finalName = formData.name.trim() || user.displayName || "Student"

      if (profileExists) {
        await userService.updateUserProfile(user.uid, {
          name: finalName,
          college: CET_COLLEGE_NAME,
          department: formData.department,
          year: formData.year,
          gender: formData.gender as "male" | "female",
          phone: formattedPhone,
        })
      } else {
        await userService.createUserProfile(user.uid, {
          name: finalName,
          email: user.email || "",
          phone: formattedPhone,
          college: CET_COLLEGE_NAME,
          department: formData.department,
          year: formData.year,
          gender: formData.gender as "male" | "female"
        })
      }

      showToast("Profile set up successfully!", "success")
      navigate("/home")
    } catch (error) {
      console.error("Error saving onboarding data:", error)
      let message = "Failed to save profile. Please try again."
      if (error instanceof Error) {
        if (error.message.includes("already registered") || error.message.includes("already in use")) {
          message = error.message
          setErrors(prev => ({ ...prev, phone: error.message }))
        } else if (error.message.includes("permission")) {
          message = "You don't have permission to update this profile."
        } else if (error.message.includes("network")) {
          message = "Unable to connect. Please check your internet connection and try again."
        } else {
          message = `Failed to save profile: ${error.message}`
        }
      }
      showToast(message, "error")
    } finally {
      setIsSaving(false)
    }
  }

  const isOnboardingLoading = authLoading || isLoading

  return (
    <MobileShell hideBottomNav className="flex flex-col space-y-5">
      {/* Title */}
      <div className="space-y-1.5 px-1">
        <h1 className="text-edex-section text-foreground font-bold tracking-tight">
          Let's set up your profile
        </h1>
        <p className="text-edex-meta text-muted-foreground">
          Enter your details to connect with peers traveling on your route.
        </p>
      </div>

      {isOnboardingLoading ? (
        <div className="space-y-4 pt-2">
          <div className="h-[300px] w-full bg-card border border-border/60 rounded-[28px] animate-pulse p-6" />
        </div>
      ) : (

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Section 1: Personal & Contact Info */}
        <div className="bg-card border border-border/60 rounded-[24px] p-5 shadow-xs space-y-4">
          <span className="text-[12px] font-extrabold text-muted-foreground uppercase tracking-wider block">
            1. Identity & Contact
          </span>

          {/* Full Name */}
          <div className="space-y-1.5">
            <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block" htmlFor="name">
              Full Name <span className="text-destructive">*</span>
            </label>
            <Input
              id="name"
              name="name"
              placeholder="E.g., Rahul Sharma"
              value={formData.name}
              onChange={handleChange}
              leftIcon={<MaterialIcon name="person_outline" className="text-[20px]" />}
              className={`h-[54px] rounded-2xl ${errors.name ? "border-destructive focus-visible:ring-destructive" : ""}`}
            />
            {errors.name && <p className="text-xs text-destructive">{errors.name}</p>}
          </div>

          {/* Gender Segmented Control */}
          <div className="space-y-2">
            <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block">
              Gender <span className="text-destructive">*</span>
            </label>
            <p className="text-[12px] text-muted-foreground leading-snug">
              Gender is used for compatible ride matching and safety controls.
            </p>
            <div className="grid grid-cols-2 gap-3 pt-1">
              <button
                type="button"
                onClick={() => {
                  setFormData(prev => ({ ...prev, gender: "male" }))
                  if (errors.gender) setErrors(prev => ({ ...prev, gender: "" }))
                }}
                className={cn(
                  "h-[54px] rounded-2xl border font-bold text-[15px] flex items-center justify-center transition-all cursor-pointer",
                  formData.gender === "male"
                    ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                    : "bg-card border-border/60 text-foreground hover:bg-muted font-semibold"
                )}
              >
                Male
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormData(prev => ({ ...prev, gender: "female" }))
                  if (errors.gender) setErrors(prev => ({ ...prev, gender: "" }))
                }}
                className={cn(
                  "h-[54px] rounded-2xl border font-bold text-[15px] flex items-center justify-center transition-all cursor-pointer",
                  formData.gender === "female"
                    ? "bg-[#C5FF00] text-black border-transparent shadow-xs font-extrabold"
                    : "bg-card border-border/60 text-foreground hover:bg-muted font-semibold"
                )}
              >
                Female
              </button>
            </div>
            {errors.gender && <p className="text-xs text-destructive">{errors.gender}</p>}
          </div>

          {/* WhatsApp Phone Number */}
          <div className="space-y-1.5 pt-1">
            <label className="text-[13px] font-bold text-muted-foreground uppercase tracking-wider block" htmlFor="phone">
              WhatsApp Phone Number <span className="text-destructive">*</span>
            </label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-sm font-semibold text-muted-foreground select-none">
                +91
              </span>
              <input
                id="phone"
                name="phone"
                type="tel"
                maxLength={10}
                placeholder="9876543210"
                value={formData.phone}
                onChange={handleChange}
                className={`w-full h-[54px] bg-card border border-border/60 rounded-2xl pl-13 pr-4 text-[16px] text-foreground font-medium focus:outline-none focus:border-foreground ${
                  errors.phone ? "border-destructive focus:border-destructive" : ""
                }`}
              />
            </div>
            <p className="text-[12px] text-muted-foreground">
              Required to coordinate rides. Only shared with confirmed co-riders.
            </p>
            {errors.phone && <p className="text-xs text-destructive">{errors.phone}</p>}
          </div>
        </div>

        {/* Section 2: Academic Details */}
        <div className="bg-card border border-border/60 rounded-[24px] p-5 shadow-xs space-y-4">
          <span className="text-[12px] font-extrabold text-muted-foreground uppercase tracking-wider block">
            2. Academic Details
          </span>

          {/* College / Institution */}
          <ThemedSelect
            id="college"
            label="College / Campus"
            required
            value={formData.college}
            options={(colleges.length > 0 ? colleges : DEFAULT_COLLEGES).map(c => ({
              value: c.name,
              label: c.name,
              badge: c.code
            }))}
            placeholder="Select your college campus"
            title="Select College Campus"
            icon={<MaterialIcon name="domain" className="text-[20px]" />}
            error={errors.college}
            onChange={(val) => {
              setFormData(prev => ({ ...prev, college: val }))
              if (errors.college) setErrors(prev => ({ ...prev, college: "" }))
            }}
          />

          {/* Department / Branch (Themed bottom sheet dropdown) */}
          <ThemedSelect
            id="department"
            label="Department / Branch"
            required
            value={formData.department}
            options={(() => {
              const matchedCollege = colleges.find(c => c.name === formData.college) || DEFAULT_COLLEGES.find(c => c.name === formData.college)
              return (matchedCollege?.departments && matchedCollege.departments.length > 0)
                ? matchedCollege.departments.map(d => ({ value: d.code, label: `${d.name} (${d.code})`, badge: d.code }))
                : CET_DEPARTMENT_OPTIONS
            })()}
            placeholder="Select your branch (e.g. ECE, CSE, ME)"
            title="Select Department / Branch"
            icon={<MaterialIcon name="school" className="text-[20px]" />}
            error={errors.department}
            onChange={handleDepartmentChange}
          />

          {/* Year of Study (Themed bottom sheet dropdown) */}
          <ThemedSelect
            id="year"
            label="Year of Study"
            required
            value={formData.year}
            options={getYearOptionsForDepartment(formData.department)}
            placeholder="Select your year of study (e.g. 4th Year)"
            title="Select Year of Study"
            icon={<MaterialIcon name="calendar_today" className="text-[20px]" />}
            error={errors.year}
            onChange={handleYearChange}
          />
        </div>

        {/* Submit Button */}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full h-14 rounded-2xl font-bold text-[16px] shadow-sm hover:opacity-90 active:scale-[0.99] transition-all cursor-pointer mt-4"
          disabled={isSaving}
        >
          {isSaving ? "Saving profile..." : "Complete Profile"}
        </Button>
      </form>
      )}
    </MobileShell>
  )
}
