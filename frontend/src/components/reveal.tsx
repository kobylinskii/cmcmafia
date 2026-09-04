"use client";

import { motion, useReducedMotion } from "motion/react";
import { ReactNode } from "react";

/**
 * Scroll-reveal stagger, canonical pattern (design-taste-frontend skill 5.C):
 * motivated by hierarchy (draw attention to content as it enters), not
 * decoration. Respects prefers-reduced-motion via useReducedMotion().
 */
export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}
