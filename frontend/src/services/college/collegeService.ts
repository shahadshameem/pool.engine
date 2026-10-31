import {
  collection,
  doc,
  getDocs,
  getDoc,
  setDoc,
  deleteDoc,
  serverTimestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"

export interface DepartmentOption {
  code: string
  name: string
}

export interface CampusLocation {
  name: string
  latitude: number
  longitude: number
}

export interface TransitHub {
  id: string
  name: string
  latitude: number
  longitude: number
}

export interface College {
  id: string
  name: string
  shortName: string
  code: string
  city: string
  state: string
  status: "active" | "onboarding" | "paused"
  allowedDomains: string[]
  location: CampusLocation
  departments: DepartmentOption[]
  transitHubs?: TransitHub[]
  studentCount?: number
  createdAt?: any
  updatedAt?: any
}

// Default Seed Campuses for Kerala Engineering Colleges
export const DEFAULT_COLLEGES: College[] = [
  {
    id: "cet",
    name: "College of Engineering Trivandrum (CET)",
    shortName: "CET Trivandrum",
    code: "CET",
    city: "Thiruvananthapuram",
    state: "Kerala",
    status: "active",
    allowedDomains: ["cet.ac.in"],
    location: {
      name: "CET Main Campus, Sreekaryam",
      latitude: 8.5458,
      longitude: 76.9032
    },
    departments: [
      { code: "CSE", name: "Computer Science & Engineering" },
      { code: "ECE", name: "Electronics & Communication" },
      { code: "EEE", name: "Electrical & Electronics" },
      { code: "ME", name: "Mechanical Engineering" },
      { code: "CE", name: "Civil Engineering" },
      { code: "AEI", name: "Applied Electronics & Instrumentation" },
      { code: "IE", name: "Industrial Engineering" },
      { code: "ARCH", name: "Architecture (B.Arch)" },
      { code: "MCA", name: "Master of Computer Applications" },
      { code: "MBA", name: "Master of Business Administration" }
    ],
    transitHubs: [
      { id: "tvm-central", name: "TVM Central Railway Station", latitude: 8.4875, longitude: 76.9525 },
      { id: "kochuveli", name: "Kochuveli Railway Station", latitude: 8.5288, longitude: 76.8970 },
      { id: "icc", name: "ICC Sreekaryam", latitude: 8.5581, longitude: 76.8816 }
    ]
  },
  {
    id: "nitc",
    name: "National Institute of Technology Calicut",
    shortName: "NIT Calicut",
    code: "NITC",
    city: "Kozhikode",
    state: "Kerala",
    status: "active",
    allowedDomains: ["nitc.ac.in", "student.nitc.ac.in"],
    location: {
      name: "NIT Calicut Campus, Kattangal",
      latitude: 11.3216,
      longitude: 75.9336
    },
    departments: [
      { code: "CSE", name: "Computer Science & Engineering" },
      { code: "ECE", name: "Electronics & Communication" },
      { code: "EEE", name: "Electrical & Electronics" },
      { code: "ME", name: "Mechanical Engineering" },
      { code: "CE", name: "Civil Engineering" },
      { code: "CHE", name: "Chemical Engineering" },
      { code: "ARCH", name: "Architecture & Planning" }
    ],
    transitHubs: [
      { id: "clt-railway", name: "Kozhikode Railway Station", latitude: 11.2480, longitude: 75.7838 },
      { id: "ksrtc-clt", name: "Kozhikode KSRTC Bus Stand", latitude: 11.2588, longitude: 75.7850 }
    ]
  },
  {
    id: "mace",
    name: "Mar Athanasius College of Engineering",
    shortName: "MACE Kothamangalam",
    code: "MACE",
    city: "Kothamangalam",
    state: "Kerala",
    status: "active",
    allowedDomains: ["mace.ac.in"],
    location: {
      name: "MACE Campus, Kothamangalam",
      latitude: 10.0538,
      longitude: 76.6193
    },
    departments: [
      { code: "CSE", name: "Computer Science & Engineering" },
      { code: "ECE", name: "Electronics & Communication" },
      { code: "EEE", name: "Electrical & Electronics" },
      { code: "ME", name: "Mechanical Engineering" },
      { code: "CE", name: "Civil Engineering" },
      { code: "MCA", name: "Master of Computer Applications" }
    ],
    transitHubs: [
      { id: "ekm-town", name: "Ernakulam Town (North) Station", latitude: 9.9926, longitude: 76.2882 },
      { id: "aluva-metro", name: "Aluva Metro Station", latitude: 10.1095, longitude: 76.3503 }
    ]
  },
  {
    id: "tkmce",
    name: "TKM College of Engineering",
    shortName: "TKM Kollam",
    code: "TKMCE",
    city: "Kollam",
    state: "Kerala",
    status: "active",
    allowedDomains: ["tkmce.ac.in"],
    location: {
      name: "TKM Campus, Karikode",
      latitude: 8.9135,
      longitude: 76.6342
    },
    departments: [
      { code: "CSE", name: "Computer Science & Engineering" },
      { code: "ECE", name: "Electronics & Communication" },
      { code: "EEE", name: "Electrical & Electronics" },
      { code: "ME", name: "Mechanical Engineering" },
      { code: "CE", name: "Civil Engineering" },
      { code: "CHE", name: "Chemical Engineering" },
      { code: "ARCH", name: "Architecture" }
    ],
    transitHubs: [
      { id: "qln-railway", name: "Kollam Junction Railway Station", latitude: 8.8845, longitude: 76.5954 }
    ]
  },
  {
    id: "gecbh",
    name: "Government Engineering College Barton Hill",
    shortName: "GEC Barton Hill",
    code: "GECBH",
    city: "Thiruvananthapuram",
    state: "Kerala",
    status: "active",
    allowedDomains: ["gecbh.ac.in"],
    location: {
      name: "GECBH Campus, Kunnukuzhy",
      latitude: 8.5136,
      longitude: 76.9366
    },
    departments: [
      { code: "CSE", name: "Computer Science & Engineering" },
      { code: "ECE", name: "Electronics & Communication" },
      { code: "EEE", name: "Electrical & Electronics" },
      { code: "ME", name: "Mechanical Engineering" },
      { code: "CE", name: "Civil Engineering" },
      { code: "IT", name: "Information Technology" }
    ]
  }
]

let collegeCache: College[] | null = null
let lastCacheTime = 0
const CACHE_TTL_MS = 3 * 60 * 1000 // 3 minutes

export const collegeService = {
  /**
   * Fetches all colleges from Firestore. If empty, falls back to default preset list.
   */
  async getColleges(onlyActive = false, forceRefresh = false): Promise<College[]> {
    const now = Date.now()
    if (!forceRefresh && collegeCache && (now - lastCacheTime < CACHE_TTL_MS)) {
      return onlyActive ? collegeCache.filter(c => c.status === "active") : collegeCache
    }

    try {
      const snap = await getDocs(collection(db, "colleges"))
      if (!snap.empty) {
        const firestoreList = snap.docs.map(d => ({ id: d.id, ...d.data() } as College))
        const firestoreIds = new Set(firestoreList.map(c => c.id.toLowerCase()))
        const merged = [
          ...firestoreList,
          ...DEFAULT_COLLEGES.filter(c => !firestoreIds.has(c.id.toLowerCase()))
        ]
        collegeCache = merged
        lastCacheTime = now
        return onlyActive ? merged.filter(c => c.status === "active") : merged
      }
    } catch (e) {
      console.warn("Could not fetch colleges from Firestore, using default presets:", e)
    }

    collegeCache = DEFAULT_COLLEGES
    lastCacheTime = now
    return onlyActive ? DEFAULT_COLLEGES.filter(c => c.status === "active") : DEFAULT_COLLEGES
  },

  /**
   * Gets a specific college by ID or short code.
   */
  async getCollegeById(id: string): Promise<College | null> {
    if (!id) return null
    const colleges = await this.getColleges(false)
    return colleges.find(c => c.id.toLowerCase() === id.toLowerCase() || c.code.toLowerCase() === id.toLowerCase()) || null
  },

  /**
   * Automatically detects college based on student's email domain.
   */
  async detectCollegeByEmail(email: string): Promise<College | null> {
    if (!email || !email.includes("@")) return null
    const domain = email.split("@")[1]?.toLowerCase().trim()
    if (!domain) return null

    const colleges = await this.getColleges(true)
    return colleges.find(c => c.allowedDomains?.some(d => domain === d.toLowerCase() || domain.endsWith("." + d.toLowerCase()))) || null
  },

  /**
   * Admin method to create a new college campus.
   */
  async createCollege(data: Omit<College, "id" | "createdAt" | "updatedAt"> & { id?: string }): Promise<string> {
    const collegeId = data.id || data.code.toLowerCase().replace(/[^a-z0-9]/g, "")
    const collegeRef = doc(db, "colleges", collegeId)

    const payload = {
      ...data,
      id: collegeId,
      status: data.status || "active",
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp()
    }

    await setDoc(collegeRef, payload, { merge: true })
    collegeCache = null
    return collegeId
  },

  /**
   * Admin method to update an existing college.
   */
  async updateCollege(id: string, data: Partial<College>): Promise<void> {
    const collegeRef = doc(db, "colleges", id)
    await setDoc(collegeRef, {
      ...data,
      updatedAt: serverTimestamp()
    }, { merge: true })
    collegeCache = null
  },

  /**
   * Admin method to delete a college.
   */
  async deleteCollege(id: string): Promise<void> {
    await deleteDoc(doc(db, "colleges", id))
    collegeCache = null
  },

  /**
   * Admin method to seed initial Kerala engineering college presets into Firestore.
   */
  async seedDefaultColleges(): Promise<number> {
    let seededCount = 0
    for (const c of DEFAULT_COLLEGES) {
      const ref = doc(db, "colleges", c.id)
      const snap = await getDoc(ref)
      if (!snap.exists()) {
        await setDoc(ref, {
          ...c,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp()
        })
        seededCount++
      }
    }
    collegeCache = null
    return seededCount
  }
}
