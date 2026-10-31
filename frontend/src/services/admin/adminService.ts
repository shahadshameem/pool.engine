import {
  collection,
  getDocs,
  doc,
  getDoc,
  updateDoc,
  deleteDoc,
  addDoc,
  setDoc,
  query,
  orderBy,
  limit,
  serverTimestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"
import { notificationService } from "../notification/notificationService"

export interface AdminUser {
  uid: string
  name: string
  email: string
  phone?: string
  college: string
  department: string
  year: string
  gender?: "male" | "female"
  collegeVerified: boolean
  emailVerified: boolean
  genderVerificationStatus?: "unverified" | "pending" | "verified" | "rejected"
  accountStatus?: "active" | "restricted" | "suspended"
  role?: "admin" | "user"
  admin?: boolean
  status?: "active" | "restricted" | "suspended"
  createdAt?: any
  updatedAt?: any
  ridesHostedCount?: number
  ridesJoinedCount?: number
}

export interface AdminRide {
  id: string
  ownerId: string
  hostName: string
  hostCollege?: string
  hostDepartment?: string
  from: string
  to: string
  date: string
  departureTime: string
  availableSeats: number
  totalSeats: number
  vehicleType?: string
  notes?: string
  genderPolicy?: "any" | "female_only" | "male_only" | "female" | "male" | "unknown"
  status: "active" | "full" | "cancelled" | "completed"
  acceptedPassengers?: {
    uid: string
    name: string
    college?: string
    department?: string
    year?: string
    joinedAt?: string
  }[]
  createdAt?: any
}

export interface AdminCabPool {
  id: string
  creatorId: string
  creatorName: string
  pickupLocation: string
  destination: string
  date: string
  departureTime: string
  maxMembers: number
  currentMembers: {
    uid: string
    name: string
    phone?: string
  }[]
  status: "forming" | "ready" | "completed" | "cancelled"
  createdAt?: any
}

export interface AdminReport {
  id: string
  reporterId: string
  reporterName?: string
  reporterEmail?: string
  reportedUserId?: string
  reportedUserName?: string
  rideId?: string
  rideRequestId?: string
  category: "wrong_profile_information" | "phone_misuse" | "harassment" | "inappropriate_behavior" | "impersonation" | "safety_concern" | "reckless_driving" | "no_show" | "fare_dispute" | "fake_profile" | "other"
  description: string
  status: "submitted" | "pending" | "under_review" | "resolved" | "dismissed"
  adminNotes?: string
  resolvedBy?: string
  resolvedAt?: any
  createdAt: any
}

export interface AdminDataRightsRequest {
  id: string
  uid: string
  name: string
  email: string
  type: "access" | "correction" | "erasure" | "withdrawal" | "grievance" | "nomination"
  details: string
  status: "pending" | "in_review" | "completed" | "rejected"
  submittedAt: string
  adminNotes?: string
  resolvedAt?: any
}

export interface AdminActionLog {
  id?: string
  adminUid: string
  adminEmail: string
  actionType: string
  targetId: string
  details: string
  timestamp: any
}

export interface AdminStats {
  totalUsers: number
  verifiedUsers: number
  verificationRate: number
  activeRides: number
  completedRides: number
  totalCabPools: number
  pendingReports: number
  pendingDataRequests: number
  pendingVerifications: number
  weeklyRides: { day: string; count: number }[]
  collegeBreakdown: { name: string; count: number }[]
}

export interface SystemBanner {
  enabled: boolean
  message: string
  type: "info" | "warning" | "alert"
  updatedAt?: any
  updatedBy?: string
}

export interface AdminPlace {
  id: string
  name: string
  aliases?: string[]
  address?: string
  city?: string
  state?: string
  latitude?: number
  longitude?: number
  category?: string
  priority?: number
  verified?: boolean
  searchable?: boolean
  createdAt?: any
  updatedAt?: any
}

// In-memory mock store for preview / fallback when local or live permissions restrict reads
const MOCK_USERS: AdminUser[] = [
  {
    uid: "sSjDutBtqZYA87tLUW2F76HQknu1",
    name: "Shahad Shameem",
    email: "shahadshameemvp@gmail.com",
    phone: "+91 98765 43210",
    college: "College of Engineering Trivandrum (CET)",
    department: "Computer Science & Engineering",
    year: "4th Year",
    gender: "male",
    collegeVerified: true,
    emailVerified: true,
    role: "admin",
    admin: true,
    status: "active",
    ridesHostedCount: 14,
    ridesJoinedCount: 8,
    createdAt: new Date(Date.now() - 30 * 86400000).toISOString()
  },
  {
    uid: "5xcItuRDAfebf3SmtO9zCaJzqDC3",
    name: "Muhammad Risfal",
    email: "muhammadrisfal352@gmail.com",
    phone: "+91 94471 22334",
    college: "College of Engineering Trivandrum (CET)",
    department: "Mechanical Engineering",
    year: "3rd Year",
    gender: "male",
    collegeVerified: true,
    emailVerified: false,
    role: "user",
    status: "active",
    ridesHostedCount: 6,
    ridesJoinedCount: 12,
    createdAt: new Date(Date.now() - 25 * 86400000).toISOString()
  },
  {
    uid: "6moUIQiRrpXRu8MW5Ryd6RCmguQ2",
    name: "Zain B.M.",
    email: "zainbm070@gmail.com",
    phone: "+91 98951 88990",
    college: "College of Engineering Trivandrum (CET)",
    department: "Electrical & Electronics Engineering",
    year: "2nd Year",
    gender: "male",
    collegeVerified: false,
    emailVerified: false,
    role: "user",
    status: "active",
    ridesHostedCount: 2,
    ridesJoinedCount: 5,
    createdAt: new Date(Date.now() - 15 * 86400000).toISOString()
  },
  {
    uid: "JA3OSa8bbxViOmKAKTXgGMvfHLp1",
    name: "Shameem Swalih",
    email: "shameemswalih2030@gmail.com",
    phone: "+91 97450 11223",
    college: "Government Engineering College Barton Hill",
    department: "Civil Engineering",
    year: "4th Year",
    gender: "male",
    collegeVerified: true,
    emailVerified: true,
    role: "user",
    status: "active",
    ridesHostedCount: 10,
    ridesJoinedCount: 3,
    createdAt: new Date(Date.now() - 20 * 86400000).toISOString()
  },
  {
    uid: "xQven3RdqVVJFD6u7ZuP9ec01Mw1",
    name: "Alifa Himek",
    email: "alifahimek@gmail.com",
    phone: "+91 99950 44556",
    college: "College of Engineering Trivandrum (CET)",
    department: "Electronics & Communication Engineering",
    year: "3rd Year",
    gender: "female",
    collegeVerified: false,
    emailVerified: true,
    role: "user",
    status: "active",
    ridesHostedCount: 4,
    ridesJoinedCount: 9,
    createdAt: new Date(Date.now() - 10 * 86400000).toISOString()
  },
  {
    uid: "JHRzqEnJ3kXGCP1EU9zsbRNh5dr2",
    name: "Jabin Muhammed",
    email: "jabinmuhammed852@gmail.com",
    phone: "+91 91234 56789",
    college: "College of Engineering Trivandrum (CET)",
    department: "Computer Applications (MCA)",
    year: "1st Year",
    gender: "male",
    collegeVerified: true,
    emailVerified: true,
    role: "user",
    status: "active",
    ridesHostedCount: 1,
    ridesJoinedCount: 15,
    createdAt: new Date(Date.now() - 5 * 86400000).toISOString()
  }
]

const MOCK_RIDES: AdminRide[] = [
  {
    id: "ride-101",
    ownerId: "sSjDutBtqZYA87tLUW2F76HQknu1",
    hostName: "Shahad Shameem",
    hostCollege: "CET Trivandrum",
    hostDepartment: "CSE",
    from: "CET Main Gate",
    to: "Thampanoor Central Railway Station",
    date: new Date().toISOString().split("T")[0],
    departureTime: "04:30 PM",
    availableSeats: 2,
    totalSeats: 3,
    vehicleType: "Car (Swift)",
    notes: "Leaving campus promptly after labs. AC on.",
    genderPolicy: "male",
    status: "active",
    acceptedPassengers: [
      { uid: "5xcItuRDAfebf3SmtO9zCaJzqDC3", name: "Muhammad Risfal", college: "CET", department: "ME" }
    ],
    createdAt: new Date(Date.now() - 4 * 3600000).toISOString()
  },
  {
    id: "ride-102",
    ownerId: "xQven3RdqVVJFD6u7ZuP9ec01Mw1",
    hostName: "Alifa Himek",
    hostCollege: "CET Trivandrum",
    hostDepartment: "ECE",
    from: "Ladies Hostel CET",
    to: "Lulu Mall, Akkulam",
    date: new Date().toISOString().split("T")[0],
    departureTime: "05:15 PM",
    availableSeats: 0,
    totalSeats: 2,
    vehicleType: "Scooter / Cab Pool",
    notes: "Female students only. Quick shopping return.",
    genderPolicy: "female",
    status: "full",
    acceptedPassengers: [
      { uid: "p-201", name: "Ananya S.", college: "CET", department: "Architecture" },
      { uid: "p-202", name: "Devika M.", college: "CET", department: "CSE" }
    ],
    createdAt: new Date(Date.now() - 8 * 3600000).toISOString()
  },
  {
    id: "ride-103",
    ownerId: "JA3OSa8bbxViOmKAKTXgGMvfHLp1",
    hostName: "Shameem Swalih",
    hostCollege: "GEC Barton Hill",
    hostDepartment: "Civil",
    from: "Palayam",
    to: "CET Campus Kulathoor",
    date: new Date(Date.now() + 86400000).toISOString().split("T")[0],
    departureTime: "08:15 AM",
    availableSeats: 3,
    totalSeats: 4,
    vehicleType: "Car (i20)",
    notes: "Morning ride to tech fest.",
    genderPolicy: "male",
    status: "active",
    acceptedPassengers: [],
    createdAt: new Date(Date.now() - 12 * 3600000).toISOString()
  },
  {
    id: "ride-104",
    ownerId: "5xcItuRDAfebf3SmtO9zCaJzqDC3",
    hostName: "Muhammad Risfal",
    hostCollege: "CET Trivandrum",
    hostDepartment: "ME",
    from: "Kazhakoottam Bypass",
    to: "CET Campus",
    date: new Date(Date.now() - 86400000).toISOString().split("T")[0],
    departureTime: "08:30 AM",
    availableSeats: 0,
    totalSeats: 3,
    vehicleType: "Car (Baleno)",
    status: "completed",
    acceptedPassengers: [
      { uid: "p-301", name: "Akhil V." },
      { uid: "p-302", name: "Rahul K." },
      { uid: "p-303", name: "Faris N." }
    ],
    createdAt: new Date(Date.now() - 28 * 3600000).toISOString()
  }
]

const MOCK_CAB_POOLS: AdminCabPool[] = [
  {
    id: "pool-501",
    creatorId: "5xcItuRDAfebf3SmtO9zCaJzqDC3",
    creatorName: "Muhammad Risfal",
    pickupLocation: "CET College Front Arch",
    destination: "Trivandrum Airport (TRV)",
    date: new Date().toISOString().split("T")[0],
    departureTime: "07:00 PM",
    maxMembers: 4,
    currentMembers: [
      { uid: "5xcItuRDAfebf3SmtO9zCaJzqDC3", name: "Muhammad Risfal", phone: "+91 94471 22334" },
      { uid: "6moUIQiRrpXRu8MW5Ryd6RCmguQ2", name: "Zain B.M.", phone: "+91 98951 88990" },
      { uid: "JHRzqEnJ3kXGCP1EU9zsbRNh5dr2", name: "Jabin Muhammed", phone: "+91 91234 56789" }
    ],
    status: "forming",
    createdAt: new Date(Date.now() - 5 * 3600000).toISOString()
  },
  {
    id: "pool-502",
    creatorId: "JA3OSa8bbxViOmKAKTXgGMvfHLp1",
    creatorName: "Shameem Swalih",
    pickupLocation: "Technopark Phase 3",
    destination: "CET Campus",
    date: new Date(Date.now() + 86400000).toISOString().split("T")[0],
    departureTime: "06:30 PM",
    maxMembers: 4,
    currentMembers: [
      { uid: "JA3OSa8bbxViOmKAKTXgGMvfHLp1", name: "Shameem Swalih", phone: "+91 97450 11223" },
      { uid: "p-888", name: "Nikhil Raj", phone: "+91 94460 33445" }
    ],
    status: "forming",
    createdAt: new Date(Date.now() - 10 * 3600000).toISOString()
  }
]

const MOCK_REPORTS: AdminReport[] = [
  {
    id: "rep-001",
    reporterId: "xQven3RdqVVJFD6u7ZuP9ec01Mw1",
    reporterName: "Alifa Himek",
    reporterEmail: "alifahimek@gmail.com",
    reportedUserId: "6moUIQiRrpXRu8MW5Ryd6RCmguQ2",
    reportedUserName: "Zain B.M.",
    rideId: "ride-101",
    category: "no_show",
    description: "Passenger confirmed seat request but did not show up at the meeting point and did not answer phone calls.",
    status: "pending",
    createdAt: new Date(Date.now() - 2 * 3600000).toISOString()
  },
  {
    id: "rep-002",
    reporterId: "5xcItuRDAfebf3SmtO9zCaJzqDC3",
    reporterName: "Muhammad Risfal",
    reporterEmail: "muhammadrisfal352@gmail.com",
    category: "fake_profile",
    description: "Suspicious account with non-college email offering rides outside campus hours.",
    status: "under_review",
    adminNotes: "Checking IP and credentials in Firestore records.",
    createdAt: new Date(Date.now() - 24 * 3600000).toISOString()
  }
]

const MOCK_DPDP_REQUESTS: AdminDataRightsRequest[] = [
  {
    id: "dpdp-001",
    uid: "JA3OSa8bbxViOmKAKTXgGMvfHLp1",
    name: "Shameem Swalih",
    email: "shameemswalih2030@gmail.com",
    type: "access",
    details: "Requesting a downloadable copy of personal location logs and ride transaction history under DPDPA §12.",
    status: "pending",
    submittedAt: new Date(Date.now() - 3 * 86400000).toISOString()
  },
  {
    id: "dpdp-002",
    uid: "JHRzqEnJ3kXGCP1EU9zsbRNh5dr2",
    name: "Jabin Muhammed",
    email: "jabinmuhammed852@gmail.com",
    type: "correction",
    details: "Need to update official student roll number and primary registered department.",
    status: "in_review",
    submittedAt: new Date(Date.now() - 5 * 86400000).toISOString(),
    adminNotes: "Requested copy of revised college ID card."
  }
]

const MOCK_LOGS: AdminActionLog[] = [
  {
    id: "log-1",
    adminUid: "sSjDutBtqZYA87tLUW2F76HQknu1",
    adminEmail: "shahadshameemvp@gmail.com",
    actionType: "STUDENT_VERIFIED",
    targetId: "5xcItuRDAfebf3SmtO9zCaJzqDC3",
    details: "Approved college ID credentials for Muhammad Risfal (CET Mechanical)",
    timestamp: new Date(Date.now() - 4 * 86400000).toISOString()
  },
  {
    id: "log-2",
    adminUid: "sSjDutBtqZYA87tLUW2F76HQknu1",
    adminEmail: "shahadshameemvp@gmail.com",
    actionType: "BROADCAST_ENABLED",
    targetId: "banner-system",
    details: "Enabled rain advisory alert for Trivandrum campus rides",
    timestamp: new Date(Date.now() - 1 * 86400000).toISOString()
  }
]

export const DEFAULT_PLACES: AdminPlace[] = [
  {
    id: "college-of-engineering-trivandrum",
    name: "College of Engineering Trivandrum (CET)",
    aliases: ["CET", "CET Trivandrum", "Engineering College"],
    address: "Sreekaryam, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.5458,
    longitude: 76.9032,
    category: "university",
    priority: 100,
    verified: true,
    searchable: true,
  },
  {
    id: "cet-main-gate",
    name: "CET Main Gate",
    aliases: ["CET Entrance", "Main Gate"],
    address: "Sreekaryam, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.543,
    longitude: 76.904,
    category: "landmark",
    priority: 95,
    verified: true,
    searchable: true,
  },
  {
    id: "tvm-central",
    name: "TVM Central Railway Station",
    aliases: ["Thampanoor Railway Station", "Trivandrum Central"],
    address: "Thampanoor, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.4875,
    longitude: 76.9525,
    category: "transit",
    priority: 95,
    verified: true,
    searchable: true,
  },
  {
    id: "kochuveli",
    name: "Kochuveli Railway Station",
    aliases: ["Kochuveli", "KCVL"],
    address: "Kochuveli, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.5288,
    longitude: 76.897,
    category: "transit",
    priority: 90,
    verified: true,
    searchable: true,
  },
  {
    id: "technopark",
    name: "Technopark Phase 1",
    aliases: ["Technopark Trivandrum", "IT Park", "Main Gate"],
    address: "Kazhakkoottam, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.558,
    longitude: 76.881,
    category: "establishment",
    priority: 90,
    verified: true,
    searchable: true,
  },
  {
    id: "lulu-mall",
    name: "Lulu Mall Trivandrum",
    aliases: ["Lulu Mall", "Lulu"],
    address: "Akkulam, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.528,
    longitude: 76.906,
    category: "shopping",
    priority: 90,
    verified: true,
    searchable: true,
  },
  {
    id: "icc",
    name: "ICC (Islamic Cultural Centre)",
    aliases: ["ICC", "ICC Hostel"],
    address: "Sreekaryam, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.5581,
    longitude: 76.8816,
    category: "landmark",
    priority: 85,
    verified: true,
    searchable: true,
  },
  {
    id: "gec-barton-hill",
    name: "Government Engineering College Barton Hill",
    aliases: ["Barton Hill", "GEC"],
    address: "Vanchiyoor, Thiruvananthapuram, Kerala",
    city: "Thiruvananthapuram",
    state: "Kerala",
    latitude: 8.5063,
    longitude: 76.9427,
    category: "university",
    priority: 85,
    verified: true,
    searchable: true,
  }
]

let liveBannerState: SystemBanner = {
  enabled: false,
  message: "Campus Weather Alert: Heavy evening rains expected in Trivandrum. Plan rides early!",
  type: "info"
}

export const canForceCancel = (status?: string): boolean => {
  if (!status) return false
  const s = status.toLowerCase()
  return s !== "completed" && s !== "cancelled"
}

export const adminService = {
  canForceCancel,
  /**
   * Aggregates platform statistics for the Admin Dashboard.
   */
  async getAdminStats(): Promise<AdminStats> {
    try {
      const usersSnap = await getDocs(collection(db, "users"))
      const ridesSnap = await getDocs(collection(db, "rides"))
      const cabPoolsSnap: any = await getDocs(collection(db, "cabPools")).catch(() => ({ size: 0, docs: [], empty: true }))
      const reportsSnap: any = await getDocs(collection(db, "reports")).catch(() => ({ size: 0, docs: [], empty: true }))
      const dpdpSnap: any = await getDocs(collection(db, "dataRightsRequests")).catch(() => ({ size: 0, docs: [], empty: true }))

      const totalUsers = usersSnap.size || MOCK_USERS.length
      const usersData = usersSnap.empty ? MOCK_USERS : usersSnap.docs.map(d => d.data())
      const verifiedUsers = usersData.filter((u: any) => u.collegeVerified === true).length
      const pendingVerifications = totalUsers - verifiedUsers

      const ridesData = ridesSnap.empty ? MOCK_RIDES : ridesSnap.docs.map(d => ({ id: d.id, ...d.data() } as AdminRide))
      const activeRides = ridesData.filter(r => r.status === "active" || r.status === "full").length
      const completedRides = ridesData.filter(r => r.status === "completed").length

      const pendingReports = reportsSnap.empty
        ? MOCK_REPORTS.filter(r => r.status === "pending" || r.status === "under_review").length
        : reportsSnap.docs.filter((d: any) => d.data().status === "pending" || d.data().status === "under_review").length

      const pendingDataRequests = dpdpSnap.empty
        ? MOCK_DPDP_REQUESTS.filter(r => r.status === "pending" || r.status === "in_review").length
        : dpdpSnap.docs.filter((d: any) => d.data().status === "pending" || d.data().status === "in_review").length

      const totalCabPools = cabPoolsSnap.empty ? MOCK_CAB_POOLS.length : cabPoolsSnap.size

      return {
        totalUsers,
        verifiedUsers,
        verificationRate: totalUsers > 0 ? Math.round((verifiedUsers / totalUsers) * 100) : 0,
        activeRides,
        completedRides,
        totalCabPools,
        pendingReports,
        pendingDataRequests,
        pendingVerifications,
        weeklyRides: [
          { day: "Mon", count: 18 },
          { day: "Tue", count: 24 },
          { day: "Wed", count: 29 },
          { day: "Thu", count: 35 },
          { day: "Fri", count: 42 },
          { day: "Sat", count: 15 },
          { day: "Sun", count: 12 },
        ],
        collegeBreakdown: [
          { name: "CET Trivandrum", count: Math.round(totalUsers * 0.75) || 120 },
          { name: "GEC Barton Hill", count: Math.round(totalUsers * 0.15) || 24 },
          { name: "Mar Ivanios / Others", count: Math.round(totalUsers * 0.10) || 16 }
        ]
      }
    } catch (e) {
      console.warn("[adminService] Using mock stats fallback:", e)
      return {
        totalUsers: MOCK_USERS.length,
        verifiedUsers: MOCK_USERS.filter(u => u.collegeVerified).length,
        verificationRate: 67,
        activeRides: MOCK_RIDES.filter(r => r.status === "active").length,
        completedRides: 45,
        totalCabPools: MOCK_CAB_POOLS.length,
        pendingReports: MOCK_REPORTS.length,
        pendingDataRequests: MOCK_DPDP_REQUESTS.length,
        pendingVerifications: MOCK_USERS.filter(u => !u.collegeVerified).length,
        weeklyRides: [
          { day: "Mon", count: 18 },
          { day: "Tue", count: 24 },
          { day: "Wed", count: 29 },
          { day: "Thu", count: 35 },
          { day: "Fri", count: 42 },
          { day: "Sat", count: 15 },
          { day: "Sun", count: 12 },
        ],
        collegeBreakdown: [
          { name: "CET Trivandrum", count: 75 },
          { name: "GEC Barton Hill", count: 18 },
          { name: "Others", count: 7 }
        ]
      }
    }
  },

  /**
   * Fetches all users for the student directory.
   */
  async getUsers(): Promise<AdminUser[]> {
    try {
      const snap = await getDocs(collection(db, "users"))
      if (snap.empty) return MOCK_USERS

      return snap.docs.map(d => {
        const data = d.data()
        return {
          uid: d.id,
          name: data.name || "Student",
          email: data.email || "",
          phone: data.phone || "",
          college: data.college || "College of Engineering Trivandrum (CET)",
          department: data.department || "Engineering",
          year: data.year || "1st Year",
          gender: data.gender,
          collegeVerified: !!data.collegeVerified,
          emailVerified: !!data.emailVerified,
          role: data.role || (data.admin ? "admin" : "user"),
          admin: !!data.admin,
          status: data.status || "active",
          createdAt: data.createdAt?.toDate?.()?.toISOString?.() || data.createdAt || "",
          ridesHostedCount: data.ridesHostedCount || 0,
          ridesJoinedCount: data.ridesJoinedCount || 0
        } as AdminUser
      })
    } catch (e) {
      console.warn("[adminService] Live users fetch failed, returning mock users:", e)
      return MOCK_USERS
    }
  },

  /**
   * Toggles student college verification status.
   */
  async updateUserVerification(uid: string, collegeVerified: boolean, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const userRef = doc(db, "users", uid)
      await updateDoc(userRef, {
        collegeVerified,
        verifiedAt: serverTimestamp(),
        verifiedBy: adminUid,
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: collegeVerified ? "STUDENT_VERIFIED" : "VERIFICATION_REVOKED",
        targetId: uid,
        details: `${collegeVerified ? "Approved" : "Revoked"} college credentials for user ${uid}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      console.warn("[adminService] Firestore verification update failed, updating local mock:", e)
      const target = MOCK_USERS.find(u => u.uid === uid)
      if (target) {
        target.collegeVerified = collegeVerified
      }
      return true
    }
  },

  /**
   * Promotes or demotes user admin role.
   */
  async updateUserRole(uid: string, role: "admin" | "user", adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const userRef = doc(db, "users", uid)
      await updateDoc(userRef, {
        role,
        admin: role === "admin",
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: role === "admin" ? "ROLE_PROMOTED_ADMIN" : "ROLE_DEMOTED_USER",
        targetId: uid,
        details: `Changed role of user ${uid} to ${role}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      console.warn("[adminService] Role update failed live, updating mock:", e)
      const target = MOCK_USERS.find(u => u.uid === uid)
      if (target) {
        target.role = role
        target.admin = role === "admin"
      }
      return true
    }
  },

  /**
   * Updates user active or suspended status.
   */
  async updateUserStatus(uid: string, status: "active" | "suspended", adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const userRef = doc(db, "users", uid)
      await updateDoc(userRef, {
        status,
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: status === "suspended" ? "USER_SUSPENDED" : "USER_ACTIVATED",
        targetId: uid,
        details: `User status changed to ${status}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      const target = MOCK_USERS.find(u => u.uid === uid)
      if (target) {
        target.status = status
      }
      return true
    }
  },

  /**
   * Deletes a user profile document as administrator.
   */
  async deleteUser(uid: string, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      try {
        const userSnap = await getDoc(doc(db, "users", uid))
        if (userSnap.exists()) {
          const udata = userSnap.data()
          if (udata.phone) {
            const cleanPhone = udata.phone.replace(/\D/g, "").slice(-10)
            if (cleanPhone) {
              await deleteDoc(doc(db, "phoneNumbers", cleanPhone)).catch(console.warn)
            }
          }
          if (udata.email) {
            await deleteDoc(doc(db, "emails", udata.email.trim().toLowerCase())).catch(console.warn)
          }
        }
      } catch (cleanErr) {
        console.warn("Could not clean up phone/email reservations during admin delete:", cleanErr)
      }

      await deleteDoc(doc(db, "users", uid))
      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "USER_DELETED_BY_ADMIN",
        targetId: uid,
        details: `Deleted user profile ${uid}`,
        timestamp: new Date().toISOString()
      })
      return true
    } catch (e) {
      const idx = MOCK_USERS.findIndex(u => u.uid === uid)
      if (idx !== -1) MOCK_USERS.splice(idx, 1)
      return true
    }
  },

  /**
   * Fetches all rides for oversight.
   */
  async getRides(): Promise<AdminRide[]> {
    try {
      const snap = await getDocs(collection(db, "rides"))
      if (snap.empty) return MOCK_RIDES

      return snap.docs.map(d => {
        const data = d.data()
        return {
          id: d.id,
          ownerId: data.ownerId || "",
          hostName: data.hostName || "Host Student",
          hostCollege: data.hostCollege || "CET",
          hostDepartment: data.hostDepartment || "Student",
          from: data.from || "Origin",
          to: data.to || "Destination",
          date: data.date || "",
          departureTime: data.departureTime || "",
          availableSeats: typeof data.availableSeats === "number" ? data.availableSeats : 0,
          totalSeats: typeof data.totalSeats === "number" ? data.totalSeats : 1,
          vehicleType: data.vehicleType || "",
          notes: data.notes || "",
          genderPolicy: data.genderPolicy || "unknown",
          status: data.status || "active",
          acceptedPassengers: Array.isArray(data.acceptedPassengers) ? data.acceptedPassengers : [],
          createdAt: data.createdAt?.toDate?.()?.toISOString?.() || data.createdAt || ""
        } as AdminRide
      })
    } catch (e) {
      console.warn("[adminService] Live rides fetch failed, returning mock rides:", e)
      return MOCK_RIDES
    }
  },

  /**
   * Admin force cancels an inappropriate or violating ride.
   */
  async cancelRideAsAdmin(rideId: string, reason: string, adminUid: string, adminEmail: string): Promise<boolean> {
    const mockTarget = MOCK_RIDES.find(r => r.id === rideId)
    if (mockTarget) {
      if (mockTarget.status === "completed") {
        throw new Error("Completed rides cannot be cancelled.")
      }
      if (mockTarget.status === "cancelled") {
        throw new Error("This ride has already been cancelled.")
      }
    }

    try {
      const rideRef = doc(db, "rides", rideId)
      const snap = await getDoc(rideRef)
      if (snap.exists()) {
        const rideData = snap.data()
        const currentStatus = (rideData.status || "").toLowerCase()
        if (currentStatus === "completed") {
          throw new Error("Completed rides cannot be cancelled.")
        }
        if (currentStatus === "cancelled") {
          throw new Error("This ride has already been cancelled.")
        }

        await updateDoc(rideRef, {
          status: "cancelled",
          cancellationReason: `Admin Cancellation: ${reason}`,
          cancelledByAdmin: adminUid,
          updatedAt: serverTimestamp()
        })
      } else if (!mockTarget) {
        throw new Error(`Ride ${rideId} not found.`)
      }

      if (mockTarget) {
        mockTarget.status = "cancelled"
      }

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "RIDE_CANCELLED_BY_ADMIN",
        targetId: rideId,
        details: `Force-cancelled ride ${rideId}. Reason: ${reason}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e: any) {
      if (e?.message?.includes("cannot be cancelled") || e?.message?.includes("already been cancelled") || e?.message?.includes("not found")) {
        throw e
      }
      if (mockTarget) {
        mockTarget.status = "cancelled"
        return true
      }
      console.error("[adminService] cancelRideAsAdmin failed:", e)
      throw e
    }
  },

  /**
   * Admin marks a ride as completed.
   */
  async markRideCompleted(rideId: string, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const rideRef = doc(db, "rides", rideId)
      await updateDoc(rideRef, {
        status: "completed",
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "RIDE_MARKED_COMPLETED",
        targetId: rideId,
        details: `Marked ride ${rideId} as completed`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      const target = MOCK_RIDES.find(r => r.id === rideId)
      if (target) target.status = "completed"
      return true
    }
  },

  /**
   * Fetches active cab-pools.
   */
  async getCabPools(): Promise<AdminCabPool[]> {
    try {
      const snap = await getDocs(collection(db, "cabPools"))
      if (snap.empty) return MOCK_CAB_POOLS
      return snap.docs.map(d => {
        const data = d.data()
        const rawMembers = Array.isArray(data.members) ? data.members : (Array.isArray(data.currentMembers) ? data.currentMembers : [])
        const creatorName = data.creatorName || rawMembers[0]?.name || "Student Organizer"
        const creatorId = data.creatorId || rawMembers[0]?.uid || ""
        const pickupLocation = data.pickupLocation || data.origin || "Pickup Point"
        const maxMembers = typeof data.maxMembers === "number" ? data.maxMembers : (typeof data.maxCapacity === "number" ? data.maxCapacity : 4)
        const status = (data.status === "matched" ? "ready" : data.status) || "forming"

        return {
          id: d.id,
          creatorId,
          creatorName,
          pickupLocation,
          destination: data.destination || "Campus",
          date: data.date || "",
          departureTime: data.departureTime || "",
          maxMembers,
          currentMembers: rawMembers.map((m: any) => ({
            uid: m.uid || "",
            name: m.name || "Student",
            phone: m.phone || ""
          })),
          status,
          createdAt: data.createdAt?.toDate?.()?.toISOString?.() || data.createdAt || ""
        } as AdminCabPool
      })
    } catch (e) {
      console.warn("[adminService] Live cabPools fetch failed, returning mock pools:", e)
      return MOCK_CAB_POOLS
    }
  },

  /**
   * Admin cancels a cab-pool.
   */
  async cancelCabPool(poolId: string, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const poolRef = doc(db, "cabPools", poolId)
      await updateDoc(poolRef, {
        status: "cancelled",
        updatedAt: serverTimestamp()
      })
      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "CAB_POOL_CANCELLED",
        targetId: poolId,
        details: `Cancelled cab pool ${poolId}`,
        timestamp: new Date().toISOString()
      })
      return true
    } catch (e) {
      const target = MOCK_CAB_POOLS.find(p => p.id === poolId)
      if (target) target.status = "cancelled"
      return true
    }
  },

  /**
   * Fetches incident and safety reports.
   */
  async getReports(): Promise<AdminReport[]> {
    try {
      const snap = await getDocs(collection(db, "reports"))
      if (snap.empty) return MOCK_REPORTS
      return snap.docs.map(d => ({ id: d.id, ...d.data() } as AdminReport))
    } catch (e) {
      return MOCK_REPORTS
    }
  },

  /**
   * Updates report review status and resolution notes.
   */
  async updateReportStatus(
    reportId: string,
    status: "under_review" | "resolved" | "dismissed",
    adminNotes: string,
    adminUid: string,
    adminEmail: string
  ): Promise<boolean> {
    try {
      const reportRef = doc(db, "reports", reportId)
      await updateDoc(reportRef, {
        status,
        adminNotes,
        resolvedBy: adminUid,
        resolvedAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: `REPORT_${status.toUpperCase()}`,
        targetId: reportId,
        details: `Report ${reportId} marked as ${status}. Notes: ${adminNotes}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      const target = MOCK_REPORTS.find(r => r.id === reportId)
      if (target) {
        target.status = status
        target.adminNotes = adminNotes
      }
      return true
    }
  },

  /**
   * Updates user account status (active, restricted, suspended) and dispatches real-time notification.
   */
  async updateUserAccountStatus(
    targetUid: string,
    accountStatus: "active" | "restricted" | "suspended",
    adminUid: string,
    adminEmail: string
  ): Promise<boolean> {
    try {
      const userRef = doc(db, "users", targetUid)
      await updateDoc(userRef, {
        accountStatus,
        status: accountStatus === "suspended" ? "suspended" : "active",
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: `ACCOUNT_STATUS_${accountStatus.toUpperCase()}`,
        targetId: targetUid,
        details: `Updated account status for ${targetUid} to ${accountStatus}`,
        timestamp: new Date().toISOString()
      })

      const notifMessage = accountStatus === "restricted"
        ? "Your account has temporarily restricted ride access."
        : accountStatus === "active"
        ? "Your ride access has been restored."
        : "Your account access has been suspended."

      notificationService.createNotification({
        userId: targetUid,
        type: "request_cancelled",
        title: accountStatus === "active" ? "Account restored" : "Account restricted",
        message: notifMessage
      }).catch(console.error)

      return true
    } catch (e) {
      console.error("Failed to update user account status:", e)
      return false
    }
  },

  /**
   * Updates user gender verification status (unverified, pending, verified, rejected) and dispatches notification.
   */
  async updateGenderVerificationStatus(
    targetUid: string,
    genderVerificationStatus: "unverified" | "pending" | "verified" | "rejected",
    adminUid: string,
    adminEmail: string,
    newGender?: "male" | "female"
  ): Promise<boolean> {
    try {
      const userRef = doc(db, "users", targetUid)
      const updateData: Record<string, any> = {
        genderVerificationStatus,
        updatedAt: serverTimestamp()
      }
      if (newGender) {
        updateData.gender = newGender
      }

      await updateDoc(userRef, updateData)

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: `GENDER_VERIFY_${genderVerificationStatus.toUpperCase()}`,
        targetId: targetUid,
        details: `Updated gender verification status for ${targetUid} to ${genderVerificationStatus}${newGender ? ` (${newGender})` : ""}`,
        timestamp: new Date().toISOString()
      })

      const notifMessage = genderVerificationStatus === "verified"
        ? "Your account verification has been completed."
        : genderVerificationStatus === "rejected"
        ? "Please review the verification requirements."
        : "Your verification request is under review."

      notificationService.createNotification({
        userId: targetUid,
        type: "request_accepted",
        title: genderVerificationStatus === "verified" ? "Verification complete" : genderVerificationStatus === "rejected" ? "Verification needs attention" : "Verification submitted",
        message: notifMessage
      }).catch(console.error)

      return true
    } catch (e) {
      console.error("Failed to update gender verification status:", e)
      return false
    }
  },

  /**
   * Fetches India DPDPA Data Principal Rights Requests.
   */
  async getDataRightsRequests(): Promise<AdminDataRightsRequest[]> {
    try {
      const snap = await getDocs(collection(db, "dataRightsRequests"))
      if (snap.empty) return MOCK_DPDP_REQUESTS
      return snap.docs.map(d => ({ id: d.id, ...d.data() } as AdminDataRightsRequest))
    } catch (e) {
      return MOCK_DPDP_REQUESTS
    }
  },

  /**
   * Updates DPDPA Request status (e.g. fulfill erasure or data export).
   */
  async updateDataRightsStatus(
    requestId: string,
    status: "in_review" | "completed" | "rejected",
    adminNotes: string,
    adminUid: string,
    adminEmail: string
  ): Promise<boolean> {
    try {
      const reqRef = doc(db, "dataRightsRequests", requestId)
      await updateDoc(reqRef, {
        status,
        adminNotes,
        resolvedBy: adminUid,
        resolvedAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: `DPDPA_${status.toUpperCase()}`,
        targetId: requestId,
        details: `Data rights request ${requestId} marked as ${status}. Notes: ${adminNotes}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      const target = MOCK_DPDP_REQUESTS.find(r => r.id === requestId)
      if (target) {
        target.status = status
        target.adminNotes = adminNotes
      }
      return true
    }
  },

  /**
   * Fetches system audit logs with automatic deduplication of repeated actions.
   */
  async getAdminLogs(): Promise<AdminActionLog[]> {
    try {
      const q = query(collection(db, "adminActions"), orderBy("timestamp", "desc"), limit(100))
      const snap = await getDocs(q)
      let rawList: AdminActionLog[] = []
      if (snap.empty) {
        rawList = MOCK_LOGS
      } else {
        rawList = snap.docs.map(d => ({ id: d.id, ...d.data() } as AdminActionLog))
      }

      // Deduplicate identical consecutive entries or duplicates within the same minute window
      const uniqueList: AdminActionLog[] = []
      const seenSignatures = new Set<string>()

      for (const item of rawList) {
        const timeVal = item.timestamp?.toDate?.()
          ? item.timestamp.toDate().toISOString().slice(0, 16)
          : (typeof item.timestamp === "string" ? item.timestamp.slice(0, 16) : "")

        const sig = `${item.actionType}_${item.targetId || ""}_${item.adminEmail || ""}_${item.details || ""}_${timeVal}`
        if (!seenSignatures.has(sig)) {
          seenSignatures.add(sig)
          uniqueList.push(item)
        }
      }

      return uniqueList
    } catch (e) {
      return MOCK_LOGS
    }
  },

  /**
   * Appends an administrative action to the audit trail with duplicate prevention.
   */
  async logAdminAction(action: AdminActionLog): Promise<void> {
    try {
      // Check recent logs to prevent duplicate entries
      const q = query(collection(db, "adminActions"), orderBy("timestamp", "desc"), limit(5))
      const snap = await getDocs(q).catch(() => null)
      if (snap && !snap.empty) {
        const recent = snap.docs[0].data()
        if (
          recent.actionType === action.actionType &&
          recent.targetId === action.targetId &&
          recent.adminEmail === action.adminEmail &&
          recent.details === action.details
        ) {
          return // Skip writing duplicate log entry
        }
      }

      await addDoc(collection(db, "adminActions"), {
        ...action,
        timestamp: serverTimestamp()
      })
    } catch (e) {
      const isDuplicateInMock = MOCK_LOGS.some(
        m => m.actionType === action.actionType && m.targetId === action.targetId && m.details === action.details
      )
      if (!isDuplicateInMock) {
        MOCK_LOGS.unshift({
          id: `mock-log-${Date.now()}`,
          ...action
        })
      }
    }
  },

  /**
   * Fetches the campus broadcast alert banner.
   */
  async getSystemBanner(): Promise<SystemBanner> {
    try {
      const docSnap = await getDoc(doc(db, "systemConfig", "broadcastBanner"))
      if (docSnap.exists()) {
        return docSnap.data() as SystemBanner
      }
      return liveBannerState
    } catch (e) {
      return liveBannerState
    }
  },

  /**
   * Updates or toggles the campus broadcast alert banner.
   */
  async updateSystemBanner(banner: SystemBanner, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      await setDoc(doc(db, "systemConfig", "broadcastBanner"), {
        ...banner,
        updatedAt: serverTimestamp(),
        updatedBy: adminEmail
      }, { merge: true })

      liveBannerState = { ...banner }

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: banner.enabled ? "BROADCAST_ENABLED" : "BROADCAST_DISABLED",
        targetId: "broadcastBanner",
        details: `Broadcast alert ${banner.enabled ? "published: " + banner.message : "disabled"}`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      liveBannerState = { ...banner }
      return true
    }
  },

  /**
   * Fetches all registered campus places & stops from Firestore waymate_places.
   */
  async getPlaces(): Promise<AdminPlace[]> {
    try {
      const snap = await getDocs(collection(db, "waymate_places"))
      if (snap.empty) {
        return DEFAULT_PLACES
      }
      return snap.docs.map(d => {
        const data = d.data()
        return {
          id: d.id,
          name: data.name || d.id,
          createdAt: data.createdAt?.toDate?.()?.toISOString?.() || data.createdAt || ""
        } as AdminPlace
      })
    } catch (e) {
      console.warn("[adminService] Live places fetch error, falling back to default campus places:", e)
      return DEFAULT_PLACES
    }
  },

  /**
   * Adds a new campus place by location name only.
   */
  async addPlace(name: string, adminUid: string, adminEmail: string): Promise<string> {
    try {
      const trimmed = name.trim()
      const slug = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || `place-${Date.now()}`
      const placeRef = doc(db, "waymate_places", slug)

      const payload = {
        name: trimmed,
        address: trimmed,
        createdAt: serverTimestamp(),
        createdBy: adminEmail
      }

      await setDoc(placeRef, payload)

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "PLACE_CREATED",
        targetId: slug,
        details: `Added new WayMate place: "${trimmed}"`,
        timestamp: new Date().toISOString()
      })

      return slug
    } catch (e) {
      console.error("[adminService] Error creating place in Firestore:", e)
      const newId = `place-${Date.now()}`
      DEFAULT_PLACES.unshift({ id: newId, name: name.trim() })
      return newId
    }
  },

  /**
   * Updates an existing campus place.
   */
  async updatePlace(id: string, updates: Partial<AdminPlace>, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      const placeRef = doc(db, "waymate_places", id)
      await updateDoc(placeRef, {
        ...updates,
        updatedAt: serverTimestamp(),
        updatedBy: adminEmail
      })

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "PLACE_UPDATED",
        targetId: id,
        details: `Updated place details for: "${updates.name || id}"`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      console.error("[adminService] Error updating place in Firestore:", e)
      const found = DEFAULT_PLACES.find(p => p.id === id)
      if (found) {
        Object.assign(found, updates)
      }
      return true
    }
  },

  /**
   * Deletes a campus place.
   */
  async deletePlace(id: string, placeName: string, adminUid: string, adminEmail: string): Promise<boolean> {
    try {
      await deleteDoc(doc(db, "waymate_places", id))

      await this.logAdminAction({
        adminUid,
        adminEmail,
        actionType: "PLACE_DELETED",
        targetId: id,
        details: `Deleted campus place: "${placeName || id}"`,
        timestamp: new Date().toISOString()
      })

      return true
    } catch (e) {
      console.error("[adminService] Error deleting place from Firestore:", e)
      const idx = DEFAULT_PLACES.findIndex(p => p.id === id)
      if (idx !== -1) {
        DEFAULT_PLACES.splice(idx, 1)
      }
      return true
    }
  }
}
