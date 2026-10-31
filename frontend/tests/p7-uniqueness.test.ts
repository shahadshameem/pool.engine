import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut } from "firebase/auth"
import { doc, deleteDoc, getDoc, setDoc } from "firebase/firestore"
import { userService } from "../src/services/user/userService"

describe("PHASE 7 — EMAIL AND PHONE NUMBER UNIQUENESS TESTS", () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  const user1Email = `p7_u1_${ts}@waymate.test`
  const user2Email = `p7_u2_${ts}@waymate.test`

  // Use randomized unique 10-digit phone numbers for this test run
  const phoneSuffix = Math.floor(100000 + Math.random() * 900000)
  const phoneA = `9895${phoneSuffix}` // e.g. 9895123456
  const phoneB = `9896${phoneSuffix}` // e.g. 9896123456

  let user1Uid = ""
  let user2Uid = ""

  const cleanups: (() => Promise<void>)[] = []

  beforeAll(async () => {
    // 1. Create User 1
    const u1Cred = await createUserWithEmailAndPassword(auth, user1Email, password)
    user1Uid = u1Cred.user.uid
    await userService.createUserProfile(user1Uid, {
      name: "User 1",
      email: user1Email,
      gender: "female",
      college: "CET",
      department: "CSE",
      year: "4th Year"
    })

    // 2. Create User 2
    const u2Cred = await createUserWithEmailAndPassword(auth, user2Email, password)
    user2Uid = u2Cred.user.uid
    await userService.createUserProfile(user2Uid, {
      name: "User 2",
      email: user2Email,
      gender: "male",
      college: "CET",
      department: "ECE",
      year: "3rd Year"
    })
  })

  afterAll(async () => {
    for (const fn of cleanups) {
      await fn().catch(() => {})
    }
    // Clean up test documents
    await deleteDoc(doc(db, "phoneNumbers", phoneA)).catch(() => {})
    await deleteDoc(doc(db, "phoneNumbers", phoneB)).catch(() => {})
    await deleteDoc(doc(db, "emails", user1Email.toLowerCase())).catch(() => {})
    await deleteDoc(doc(db, "emails", user2Email.toLowerCase())).catch(() => {})
    await deleteDoc(doc(db, "users", user1Uid)).catch(() => {})
    await deleteDoc(doc(db, "users", user2Uid)).catch(() => {})
    await signOut(auth).catch(() => {})
  })

  it("P7-U1: User 1 can claim and set a valid 10-digit phone number", async () => {
    await signInWithEmailAndPassword(auth, user1Email, password)

    // User 1 sets phoneA
    await userService.updateUserProfile(user1Uid, { phone: phoneA })

    // Verify phone is recorded in user profile
    const profile = await userService.getUserProfile(user1Uid, true)
    expect(profile?.phone).toBe(phoneA)

    // Verify phone is registered in phoneNumbers collection
    const phoneDoc = await getDoc(doc(db, "phoneNumbers", phoneA))
    expect(phoneDoc.exists()).toBe(true)
    expect(phoneDoc.data()?.uid).toBe(user1Uid)
  })

  it("P7-U2: User 2 is rejected by userService when attempting to use User 1's phone number", async () => {
    await signInWithEmailAndPassword(auth, user2Email, password)

    let errorOccurred = false
    let errorMessage = ""
    try {
      await userService.updateUserProfile(user2Uid, { phone: phoneA })
    } catch (err: any) {
      errorOccurred = true
      errorMessage = err?.message || ""
    }

    expect(errorOccurred).toBe(true)
    expect(errorMessage).toContain("already registered to another account")

    // Verify User 2's profile was not changed to phoneA
    const profile2 = await userService.getUserProfile(user2Uid, true)
    expect(profile2?.phone).not.toBe(phoneA)
  })

  it("P7-U3: Firestore Security Rule blocks User 2 from directly writing User 1's phone number to users collection", async () => {
    await signInWithEmailAndPassword(auth, user2Email, password)

    // Attempt direct bypass of userService
    let permissionDenied = false
    try {
      await setDoc(doc(db, "users", user2Uid), { phone: phoneA }, { merge: true })
    } catch (err: any) {
      permissionDenied = true
      expect(err?.message || "").toMatch(/permission|insufficient/i)
    }

    expect(permissionDenied).toBe(true)
  })

  it("P7-U4: Firestore Security Rule blocks User 2 from setting an email that does not match their auth token", async () => {
    await signInWithEmailAndPassword(auth, user2Email, password)

    // Attempt to hijack/spoof User 1's email in User 2's document
    let permissionDenied = false
    try {
      await setDoc(doc(db, "users", user2Uid), { email: user1Email }, { merge: true })
    } catch (err: any) {
      permissionDenied = true
      expect(err?.message || "").toMatch(/permission|insufficient/i)
    }

    expect(permissionDenied).toBe(true)
  })

  it("P7-U5: When User 1 changes phone from phoneA to phoneB, phoneA is released and can be claimed by User 2", async () => {
    // 1. User 1 updates phone to phoneB
    await signInWithEmailAndPassword(auth, user1Email, password)
    await userService.updateUserProfile(user1Uid, { phone: phoneB })

    const p1 = await userService.getUserProfile(user1Uid, true)
    expect(p1?.phone).toBe(phoneB)

    // Verify phoneA reservation was released
    const oldPhoneDoc = await getDoc(doc(db, "phoneNumbers", phoneA))
    expect(oldPhoneDoc.exists()).toBe(false)

    // 2. User 2 can now claim phoneA without error
    await signInWithEmailAndPassword(auth, user2Email, password)
    await userService.updateUserProfile(user2Uid, { phone: phoneA })

    const p2 = await userService.getUserProfile(user2Uid, true)
    expect(p2?.phone).toBe(phoneA)

    const newClaimDoc = await getDoc(doc(db, "phoneNumbers", phoneA))
    expect(newClaimDoc.exists()).toBe(true)
    expect(newClaimDoc.data()?.uid).toBe(user2Uid)
  })
})
