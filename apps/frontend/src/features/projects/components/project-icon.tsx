import Image from "next/image";
import {
  projectIconSources,
  type ProjectIconName,
} from "../config/project-icon-sources";

export type { ProjectIconName } from "../config/project-icon-sources";

interface ProjectIconProps {
  className?: string;
  name: ProjectIconName;
  size?: number;
}

export function ProjectIcon({ className = "", name, size = 16 }: ProjectIconProps) {
  return (
    <Image
      alt=""
      aria-hidden="true"
      className={className}
      height={size}
      src={projectIconSources[name]}
      style={{ flex: "none", height: size, objectFit: "contain", width: size }}
      width={size}
    />
  );
}
