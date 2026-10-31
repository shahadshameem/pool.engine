import { useNavigate } from "react-router-dom"
import { Button } from "../ui/button"
import { MaterialIcon } from "../common/MaterialIcon"

export function WelcomeActions() {
  const navigate = useNavigate()

  return (
    <div className="flex w-full flex-col items-center space-y-4 px-4 pb-8">
      <Button
        variant="primary"
        size="lg"
        className="w-full flex items-center justify-center space-x-2"
        onClick={() => navigate("/login")}
      >
        <span>Get Started</span>
        <MaterialIcon name="arrow_forward" className="text-[20px]" />
      </Button>

      <div className="text-[15px] text-muted-foreground">
        Already have an account?{" "}
        <button
          onClick={() => navigate("/login")}
          className="font-bold text-foreground dark:text-[#C5FF00] underline underline-offset-4 hover:opacity-80 cursor-pointer"
        >
          Sign in
        </button>
      </div>
    </div>
  )
}
