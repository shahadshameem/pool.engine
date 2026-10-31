import { createContext, useEffect, useState } from "react"
import type { User } from "firebase/auth"
import { onAuthStateChanged } from "firebase/auth"
import { doc, getDoc, onSnapshot, setDoc, serverTimestamp } from "firebase/firestore"
import { auth, db } from "../config/firebase"
import type { UserProfile } from "../services/user/userService"
import { isDevMockEnabled } from "../utils/devMock"

interface AuthContextType {
  user: User | null
  profile: UserProfile | null
  loading: boolean        // true until Firebase Auth resolves
  profileLoading: boolean // true until Firestore profile snapshot resolves
  isAuthenticated: boolean
}

export const AuthContext = createContext<AuthContextType>({
  user: null,
  profile: null,
  loading: true,
  profileLoading: true,
  isAuthenticated: false,
})

const ENV_ADMIN_EMAILS: string[] = ((import.meta.env.VITE_ADMIN_EMAILS as string) || "")
  .split(",")
  .map(e => e.trim().toLowerCase())
  .filter(Boolean)

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const isMock = isDevMockEnabled()
  const [user, setUser] = useState<User | null>(isMock ? ({ uid: "mock-user-123", email: "student@cet.ac.in" } as User) : null)
  const [profile, setProfile] = useState<UserProfile | null>(isMock ? ({ uid: "mock-user-123", name: "Alex Student", gender: "male", college: "CET Trivandrum" } as UserProfile) : null)
  const [loading, setLoading] = useState(!isMock)
  const [profileLoading, setProfileLoading] = useState(!isMock)

  useEffect(() => {
    if (isMock) return

    const unsubscribeAuth = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser)
      setLoading(false)
    })

    return () => unsubscribeAuth()
  }, [isMock])

  useEffect(() => {
    if (isMock) return

    if (!user?.uid) {
      setProfile(null)
      setProfileLoading(false)
      return
    }

    setProfileLoading(true)
    const unsubscribeProfile = onSnapshot(
      doc(db, "users", user.uid),
      async (docSnap) => {
        if (docSnap.exists()) {
          const data = docSnap.data()
          // Self-heal: If profile in Firestore has "Student" or "User" or empty, resolve to real Google displayName
          const realName = (data.name && data.name !== "Student" && data.name !== "User")
            ? data.name
            : (user.displayName || (user.email ? user.email.split("@")[0] : "") || data.name || "User")

          if (user.displayName && (!data.name || data.name === "Student" || data.name === "User")) {
            setDoc(doc(db, "users", user.uid), { name: user.displayName }, { merge: true }).catch(console.error)
          }

          // DPDPA Privacy: Fetch phone from users/{uid}/private/contact with fallback to root doc
          let userPhone = data.phone || user.phoneNumber || ""
          try {
            const contactSnap = await getDoc(doc(db, "users", user.uid, "private", "contact"))
            if (contactSnap.exists() && contactSnap.data()?.phone) {
              userPhone = contactSnap.data().phone
            } else if (userPhone) {
              // Auto-sync legacy root phone to private/contact
              setDoc(doc(db, "users", user.uid, "private", "contact"), {
                uid: user.uid,
                phone: userPhone,
                updatedAt: serverTimestamp()
              }, { merge: true }).catch(() => {})
            }
          } catch {}

          setProfile({ uid: user.uid, ...data, phone: userPhone, name: realName } as UserProfile)
        } else {
          // Self-heal: If user is an admin whitelisted email whose profile doc was deleted, auto-recreate admin doc
          const userEmailLower = (user.email || "").toLowerCase().trim()
          const isAdminEmail = ENV_ADMIN_EMAILS.includes(userEmailLower)
          const fallbackName = user.displayName || user.email?.split("@")[0] || "User"

          if (isAdminEmail) {
            const adminDocData = {
              uid: user.uid,
              name: fallbackName,
              email: user.email || userEmailLower,
              phone: user.phoneNumber || "",
              college: "College of Engineering Trivandrum (CET)",
              department: "Electronics & Communication Engineering",
              year: "4th Year",
              role: "admin",
              admin: true,
              emailVerified: true,
              collegeVerified: true,
              createdAt: serverTimestamp(),
              updatedAt: serverTimestamp()
            }
            setDoc(doc(db, "users", user.uid), adminDocData, { merge: true }).catch(console.error)
            setProfile(adminDocData as UserProfile)
          } else {
            // Provide fallback profile so UI doesn't stall on loading
            setProfile({
              uid: user.uid,
              name: fallbackName,
              email: user.email || "",
              phone: user.phoneNumber || "",
              college: "College of Engineering Trivandrum (CET)",
              department: "Engineering",
              year: "1",
              emailVerified: user.emailVerified,
              collegeVerified: true
            } as UserProfile)
          }
        }
        setProfileLoading(false)
      },
      (error) => {
        console.error("Profile snapshot error:", error)
        const fallbackName = user.displayName || user.email?.split("@")[0] || "User"
        setProfile({
          uid: user.uid,
          name: fallbackName,
          email: user.email || "",
          phone: user.phoneNumber || "",
          college: "College of Engineering Trivandrum (CET)",
          department: "Engineering",
          year: "1",
          emailVerified: user.emailVerified,
          collegeVerified: true
        } as UserProfile)
        setProfileLoading(false)
      }
    )

    return () => unsubscribeProfile()
  }, [user?.uid, isMock])

  return (
    <AuthContext.Provider value={{
      user,
      profile,
      loading,
      profileLoading,
      isAuthenticated: !!user && !!profile
    }}>
      {children}
    </AuthContext.Provider>
  )
}
