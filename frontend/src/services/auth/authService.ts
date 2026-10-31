import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signOut as firebaseSignOut,
  sendEmailVerification as firebaseSendEmailVerification,
  sendPasswordResetEmail,
  GoogleAuthProvider,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult
} from "firebase/auth"
import type { User, MultiFactorResolver } from "firebase/auth"
import { doc, getDoc, setDoc, serverTimestamp } from "firebase/firestore"
import { auth, db } from "../../config/firebase"
import { mfaService, formatToE164 } from "./mfaService"

export { formatToE164 }

const googleProvider = new GoogleAuthProvider()
googleProvider.setCustomParameters({
  prompt: "select_account"
})

export interface AuthError {
  code: string
  message: string
  resolver?: MultiFactorResolver | null
  rawError?: any
}

export const authService = {
  /**
   * Primary Authentication: Sign in with Google via Firebase Authentication.
   * Tries popup flow first; automatically falls back to redirect if popup is blocked.
   */
  async signInWithGoogle(): Promise<{ user: User }> {
    try {
      let userCredential: any = null
      try {
        userCredential = await signInWithPopup(auth, googleProvider)
      } catch (popupErr: any) {
        if (
          popupErr?.code === "auth/popup-blocked" ||
          popupErr?.code === "auth/cancelled-popup-request"
        ) {
          console.warn("[Google Auth] Popup blocked or cancelled, attempting signInWithRedirect...")
          await signInWithRedirect(auth, googleProvider)
          // For redirect, page will reload; return current user if available
          return { user: auth.currentUser! }
        }
        throw popupErr
      }

      const user: User = userCredential.user
      await this.ensureUserProfile(user)
      return { user }
    } catch (error: any) {
      console.error("[Google Auth] Sign-in error:", error)
      const resolver = mfaService.getResolver(error)
      throw {
        code: error?.code || "auth/google-sign-in-failed",
        message: this.normalizeErrorMessage(error),
        resolver,
        rawError: error
      } as AuthError
    }
  },

  /**
   * Checks for a pending redirect result upon page load (if signInWithRedirect was used).
   */
  async handleRedirectResult(): Promise<User | null> {
    try {
      const result = await getRedirectResult(auth)
      if (result && result.user) {
        await this.ensureUserProfile(result.user)
        return result.user
      }
      return null
    } catch (error) {
      console.warn("[Google Auth] Redirect result resolution:", error)
      return null
    }
  },

  /**
   * Ensures a basic user profile document exists in Firestore for the authenticated Google user.
   * Preserves existing profile data without overwriting verified fields.
   */
  async ensureUserProfile(user: User): Promise<void> {
    try {
      const userRef = doc(db, "users", user.uid)
      const userSnap = await getDoc(userRef)

      const googleName = user.displayName || (user.email ? user.email.split("@")[0] : "") || "User"

      if (!userSnap.exists()) {
        await setDoc(userRef, {
          uid: user.uid,
          name: googleName,
          email: user.email || "",
          phone: "", // Keep phone empty at root to satisfy security rules
          gender: "", // Set during onboarding
          college: "College of Engineering Trivandrum (CET)",
          department: "",
          year: "",
          emailVerified: false,
          collegeVerified: false,
          genderVerificationStatus: "unverified",
          accountStatus: "active",
          role: "user",
          admin: false,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
      } else {
        // Sync Google displayName if existing profile name is generic/empty
        const existingData = userSnap.data()
        const updates: Record<string, any> = {}
        if (googleName && (!existingData.name || existingData.name === "Student" || existingData.name === "User")) {
          updates.name = googleName
        }
        if (user.email && !existingData.email) {
          updates.email = user.email
        }
        if (Object.keys(updates).length > 0) {
          updates.updatedAt = serverTimestamp()
          await setDoc(userRef, updates, { merge: true })
        }
      }
    } catch (profileErr) {
      console.error("[Google Auth] Error ensuring user profile:", profileErr)
    }
  },

  /**
   * Translates Firebase error codes into friendly user messages.
   */
  normalizeErrorMessage(error: any): string {
    const code = error?.code || ""
    switch (code) {
      case "auth/popup-closed-by-user":
      case "auth/cancelled-popup-request":
        return "Sign-in was cancelled."
      case "auth/popup-blocked":
        return "Sign-in popup was blocked by your browser. Please allow popups for this site."
      case "auth/network-request-failed":
        return "Network connection failed. Please check your internet connection and try again."
      case "auth/unauthorized-domain":
        return "This domain is not authorized in Firebase Console. Please add it to Authorized Domains in Firebase Authentication."
      case "auth/account-exists-with-different-credential":
        return "An account already exists with the same email using a different sign-in method."
      case "auth/user-disabled":
        return "This account has been disabled. Please contact support."
      default:
        return error?.message || "Failed to sign in. Please try again."
    }
  },

  async signUp(email: string, password: string): Promise<User> {
    try {
      const userCredential = await createUserWithEmailAndPassword(auth, email, password)
      return userCredential.user
    } catch (error: any) {
      throw { code: error.code, message: error.message, rawError: error } as AuthError
    }
  },

  async signIn(email: string, password: string): Promise<User> {
    try {
      const userCredential = await signInWithEmailAndPassword(auth, email, password)
      return userCredential.user
    } catch (error: any) {
      const resolver = mfaService.getResolver(error)
      throw {
        code: error.code,
        message: error.message,
        resolver,
        rawError: error
      } as AuthError
    }
  },

  async signOut(): Promise<void> {
    try {
      await firebaseSignOut(auth)
    } catch (error: any) {
      throw { code: error.code, message: error.message } as AuthError
    }
  },

  async sendPasswordReset(email: string): Promise<void> {
    try {
      await sendPasswordResetEmail(auth, email)
    } catch (error: any) {
      throw { code: error.code, message: error.message } as AuthError
    }
  },

  async sendVerification(user: User): Promise<void> {
    try {
      await firebaseSendEmailVerification(user)
    } catch (error: any) {
      throw { code: error.code, message: error.message } as AuthError
    }
  }
}
