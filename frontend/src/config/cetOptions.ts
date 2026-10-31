export const CET_COLLEGE_NAME = "College of Engineering Trivandrum (CET)"

export const CET_DEPARTMENT_OPTIONS = [
  { value: "CSE", label: "Computer Science & Engineering (CSE)", badge: "CSE" },
  { value: "ECE", label: "Electronics & Communication (ECE)", badge: "ECE" },
  { value: "EEE", label: "Electrical & Electronics (EEE)", badge: "EEE" },
  { value: "ME", label: "Mechanical Engineering (ME)", badge: "ME" },
  { value: "CE", label: "Civil Engineering (CE)", badge: "CE" },
  { value: "AEI", label: "Applied Electronics & Instrumentation (AEI)", badge: "AEI" },
  { value: "IE", label: "Industrial Engineering (IE)", badge: "IE" },
  { value: "ARCH", label: "Architecture (B.Arch)", badge: "ARCH" },
  { value: "MCA", label: "Master of Computer Applications (MCA)", badge: "MCA" },
  { value: "MBA", label: "Master of Business Administration (MBA)", badge: "MBA" },
]

export const CET_YEAR_OPTIONS = [
  { value: "1st Year", label: "1st Year (S1 / S2)", badge: "1st" },
  { value: "2nd Year", label: "2nd Year (S3 / S4)", badge: "2nd" },
  { value: "3rd Year", label: "3rd Year (S5 / S6)", badge: "3rd" },
  { value: "4th Year", label: "4th Year (S7 / S8)", badge: "4th" },
  { value: "5th Year", label: "5th Year (B.Arch)", badge: "5th" },
  { value: "PG / Scholar", label: "Post Graduate / M.Tech / PhD", badge: "PG" },
]

export function getYearOptionsForDepartment(deptValue?: string) {
  const isArch = deptValue === "ARCH" || (deptValue ? deptValue.toLowerCase().includes("arch") : false)
  if (isArch) {
    return CET_YEAR_OPTIONS
  }
  return CET_YEAR_OPTIONS.filter((y) => y.value !== "5th Year")
}
