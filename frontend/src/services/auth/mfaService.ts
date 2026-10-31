import {
  multiFactor,
  PhoneAuthProvider,
  PhoneMultiFactorGenerator,
  RecaptchaVerifier,
  getMultiFactorResolver,
  type User,
  type MultiFactorResolver,
  type MultiFactorInfo
} from "firebase/auth"
import { doc, setDoc, serverTimestamp } from "firebase/firestore"
import { auth, db } from "../../config/firebase"

export interface MfaEnrollmentState {
  isEnrolled: boolean
  enrolledPhone?: string
  factors: MultiFactorInfo[]
}

/**
 * Normalizes any Indian/international phone string to canonical E.164 (+91XXXXXXXXXX)
 */
export function formatToE164(phone: string): string {
  if (!phone) return ""
  let clean = phone.replace(/[^\d+]/g, "")
  if (clean.startsWith("+")) {
    return clean
  }
  const digitsOnly = clean.replace(/\D/g, "")
  if (digitsOnly.length === 10) {
    return `+91${digitsOnly}`
  }
  if (digitsOnly.length === 12 && digitsOnly.startsWith("91")) {
    return `+${digitsOnly}`
  }
  return `+${digitsOnly}`
}

/**
 * Initializes or resets a RecaptchaVerifier on a DOM element.
 */
export function createRecaptchaVerifier(
  containerId: string = "mfa-recaptcha-container",
  invisible: boolean = true
): RecaptchaVerifier {
  if (typeof window === "undefined") {
    throw new Error("RecaptchaVerifier requires a browser window environment")
  }

  // Clear existing verifier if stored on window
  const win = window as any
  if (win.__waymate_recaptcha_verifier) {
    try {
      win.__waymate_recaptcha_verifier.clear()
    } catch {}
    win.__waymate_recaptcha_verifier = null
  }

  // Ensure target container exists in DOM; if not, create an off-screen container
  let containerEl = document.getElementById(containerId)
  if (!containerEl) {
    containerEl = document.createElement("div")
    containerEl.id = containerId
    containerEl.style.position = "fixed"
    containerEl.style.bottom = "0"
    containerEl.style.right = "0"
    containerEl.style.zIndex = "-1"
    document.body.appendChild(containerEl)
  }

  const verifier = new RecaptchaVerifier(auth, containerId, {
    size: invisible ? "invisible" : "normal",
    callback: () => {
      // reCAPTCHA solved - allow phone verification
    },
    "expired-callback": () => {
      console.warn("[MFA] Recaptcha response expired. Regenerating...")
    }
  })

  win.__waymate_recaptcha_verifier = verifier
  return verifier
}

export const mfaService = {
  /**
   * Check whether a given user has SMS MFA enrolled.
   */
  isMfaEnrolled(user: User | null): boolean {
    if (!user) return false
    try {
      const directFactors = (user as any)?.multiFactor?.enrolledFactors
      if (Array.isArray(directFactors)) {
        return directFactors.length > 0
      }
      const factors = multiFactor(user).enrolledFactors
      return Array.isArray(factors) && factors.length > 0
    } catch {
      return false
    }
  },

  /**
   * Get list of enrolled multi-factor info objects for a user.
   */
  getEnrolledFactors(user: User | null): MultiFactorInfo[] {
    if (!user) return []
    try {
      const directFactors = (user as any)?.multiFactor?.enrolledFactors
      if (Array.isArray(directFactors)) {
        return directFactors
      }
      return multiFactor(user).enrolledFactors || []
    } catch {
      return []
    }
  },

  /**
   * Step 1 of Enrollment: Send SMS OTP to phone number.
   * Returns verificationId needed for step 2.
   */
  async startPhoneEnrollment(
    user: User,
    rawPhoneNumber: string,
    recaptchaVerifier: RecaptchaVerifier
  ): Promise<{ verificationId: string; formattedPhone: string }> {
    const formattedPhone = formatToE164(rawPhoneNumber)
    if (!formattedPhone || formattedPhone.length < 11) {
      throw new Error("Please enter a valid phone number with country code")
    }

    const multiFactorSession = await multiFactor(user).getSession()
    const phoneAuthProvider = new PhoneAuthProvider(auth)

    const verificationId = await phoneAuthProvider.verifyPhoneNumber(
      {
        phoneNumber: formattedPhone,
        session: multiFactorSession
      },
      recaptchaVerifier
    )

    return { verificationId, formattedPhone }
  },

  /**
   * Step 2 of Enrollment: Submit SMS verification OTP to enroll factor.
   */
  async finishPhoneEnrollment(
    user: User,
    verificationId: string,
    verificationCode: string,
    displayName: string = "Primary Phone"
  ): Promise<void> {
    const cred = PhoneAuthProvider.credential(verificationId, verificationCode.trim())
    const assertion = PhoneMultiFactorGenerator.assertion(cred)

    await multiFactor(user).enroll(assertion, displayName)

    // Sync MFA enabled state to Firestore user profile
    try {
      await setDoc(
        doc(db, "users", user.uid),
        {
          mfaEnabled: true,
          mfaEnrolledAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        },
        { merge: true }
      )
    } catch (e) {
      console.warn("[MFA] Failed to sync mfaEnabled flag to Firestore:", e)
    }
  },

  /**
   * Unenroll / Disable SMS Multi-Factor Authentication for the user.
   */
  async unenrollMfa(user: User, factorUid?: string): Promise<void> {
    const factors = multiFactor(user).enrolledFactors
    if (!factors || factors.length === 0) return

    if (factorUid) {
      const target = factors.find((f) => f.uid === factorUid)
      if (target) {
        await multiFactor(user).unenroll(target)
      }
    } else {
      // Unenroll all enrolled factors
      for (const factor of factors) {
        await multiFactor(user).unenroll(factor)
      }
    }

    // Sync disabled state to Firestore
    try {
      const remaining = multiFactor(user).enrolledFactors
      if (remaining.length === 0) {
        await setDoc(
          doc(db, "users", user.uid),
          {
            mfaEnabled: false,
            mfaUnenrolledAt: serverTimestamp(),
            updatedAt: serverTimestamp()
          },
          { merge: true }
        )
      }
    } catch (e) {
      console.warn("[MFA] Failed to update Firestore on unenroll:", e)
    }
  },

  /**
   * Helper to parse Firebase Auth error into MultiFactorResolver if required.
   */
  getResolver(error: any): MultiFactorResolver | null {
    if (error?.code === "auth/multi-factor-auth-required") {
      try {
        return getMultiFactorResolver(auth, error)
      } catch (e) {
        console.error("[MFA] Failed to get resolver from error:", e)
      }
    }
    return null
  },

  /**
   * Sign-in Step 1 (Second Factor Challenge):
   * Sends SMS code to the enrolled phone number hint in the resolver.
   */
  async sendSignInMfaCode(
    resolver: MultiFactorResolver,
    recaptchaVerifier: RecaptchaVerifier,
    selectedHintIndex: number = 0
  ): Promise<{ verificationId: string; maskedPhoneNumber: string }> {
    const phoneInfo = resolver.hints[selectedHintIndex] || resolver.hints[0]
    if (!phoneInfo) {
      throw new Error("No phone factor found for this account")
    }

    const phoneAuthProvider = new PhoneAuthProvider(auth)
    const verificationId = await phoneAuthProvider.verifyPhoneNumber(
      {
        multiFactorHint: phoneInfo,
        session: resolver.session
      },
      recaptchaVerifier
    )

    const masked = (phoneInfo as any).phoneNumber || "your registered phone"
    return { verificationId, maskedPhoneNumber: masked }
  },

  /**
   * Sign-in Step 2: Complete multi-factor sign-in with received SMS code.
   */
  async completeSignInWithMfa(
    resolver: MultiFactorResolver,
    verificationId: string,
    verificationCode: string
  ): Promise<User> {
    const cred = PhoneAuthProvider.credential(verificationId, verificationCode.trim())
    const assertion = PhoneMultiFactorGenerator.assertion(cred)

    const userCredential = await resolver.resolveSignIn(assertion)
    return userCredential.user
  }
}
