import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword, signOut } from "firebase/auth"
import { doc, deleteDoc, getDoc } from "firebase/firestore"
import { collegeService, DEFAULT_COLLEGES } from "../src/services/college/collegeService"
import { userService } from "../src/services/user/userService"

describe("PHASE 8 — MULTI-COLLEGE PLATFORM TESTS", { timeout: 30000 }, () => {
  const ts = Date.now()
  const password = "TestPassword123!"
  const testAdminEmail = "admin@waymate.test"
  const testCollegeId = `test_col_${ts}`
  let testAdminUid = ""

  beforeAll(async () => {
    // Create or sign in as test admin
    let cred: any
    try {
      cred = await createUserWithEmailAndPassword(auth, testAdminEmail, password)
    } catch (e: any) {
      if (e.code === "auth/email-already-in-use") {
        cred = await signInWithEmailAndPassword(auth, testAdminEmail, password)
      } else {
        throw e
      }
    }
    testAdminUid = cred.user.uid

    // Set admin custom claim via Firebase Auth Emulator API
    await fetch("http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:update?key=fake-api-key", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer owner"
      },
      body: JSON.stringify({
        localId: testAdminUid,
        customAttributes: JSON.stringify({ admin: true })
      })
    })
    await signInWithEmailAndPassword(auth, testAdminEmail, password)
    await cred.user.getIdToken(true)

    await userService.createUserProfile(testAdminUid, {
      name: "Test Admin",
      email: testAdminEmail,
      college: "College of Engineering Trivandrum (CET)",
      department: "CSE",
      year: "4th Year"
    })

    // Seed default colleges into Firestore if not present
    await collegeService.seedDefaultColleges().catch(() => {})
    await collegeService.updateCollege("nitc", { status: "active" }).catch(() => {})
    await collegeService.updateCollege("mace", { status: "active" }).catch(() => {})
  }, 30000)

  afterAll(async () => {
    await deleteDoc(doc(db, "colleges", testCollegeId)).catch(() => {})
    await deleteDoc(doc(db, "users", testAdminUid)).catch(() => {})
    await signOut(auth).catch(() => {})
  }, 30000)

  it("P8-M1: Fetching active colleges returns default Kerala campus presets", async () => {
    const list = await collegeService.getColleges(true, true)
    expect(list.length).toBeGreaterThan(0)
    expect(list.some(c => c.code === "CET")).toBe(true)
    expect(list.some(c => c.code === "NITC")).toBe(true)
    expect(list.some(c => c.code === "MACE")).toBe(true)
  })

  it("P8-M2: Email domain auto-detection correctly maps student emails to target colleges", async () => {
    const cetMatch = await collegeService.detectCollegeByEmail("arun@cet.ac.in")
    expect(cetMatch).not.toBeNull()
    expect(cetMatch?.code).toBe("CET")

    const nitcMatch = await collegeService.detectCollegeByEmail("rahul@student.nitc.ac.in")
    expect(nitcMatch).not.toBeNull()
    expect(nitcMatch?.code).toBe("NITC")

    const maceMatch = await collegeService.detectCollegeByEmail("fathima@mace.ac.in")
    expect(maceMatch).not.toBeNull()
    expect(maceMatch?.code).toBe("MACE")
  })

  it("P8-M3: Admin can onboard a new custom college and configure allowed domains and departments", async () => {
    // Create custom test college
    const createdId = await collegeService.createCollege({
      id: testCollegeId,
      name: `Test Engineering College ${ts}`,
      shortName: "TEC",
      code: `TEC${ts.toString().slice(-4)}`,
      city: "Kochi",
      state: "Kerala",
      status: "active",
      allowedDomains: ["tec.edu.in"],
      location: {
        name: "TEC Campus Kochi",
        latitude: 9.9312,
        longitude: 76.2673
      },
      departments: [
        { code: "CSE", name: "Computer Science" },
        { code: "AI", name: "Artificial Intelligence" }
      ]
    })

    expect(createdId).toBe(testCollegeId)

    // Verify written doc in Firestore
    const colDoc = await getDoc(doc(db, "colleges", testCollegeId))
    expect(colDoc.exists()).toBe(true)
    expect(colDoc.data()?.name).toContain("Test Engineering College")

    // Test email domain detection for new custom college
    const match = await collegeService.detectCollegeByEmail("student@tec.edu.in")
    expect(match).not.toBeNull()
    expect(match?.id).toBe(testCollegeId)
  })

  it("P8-M4: Admin can update college status between active, onboarding, and paused", async () => {
    // Update to paused
    await collegeService.updateCollege(testCollegeId, { status: "paused" })

    const updatedCol = await collegeService.getCollegeById(testCollegeId)
    expect(updatedCol?.status).toBe("paused")

    // Clean up
    await collegeService.deleteCollege(testCollegeId)
    const deletedDoc = await getDoc(doc(db, "colleges", testCollegeId))
    expect(deletedDoc.exists()).toBe(false)
  })
})
