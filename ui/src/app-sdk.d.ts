// Ambient declarations for the host-provided @kirocrew/app-sdk.
// The SDK is NOT installed as an npm dependency: the Crew host provides it at
// runtime and Vite treats it as a rollup external. These declarations exist
// only so tsc/vite can typecheck the imports without the real package.

declare module '@kirocrew/app-sdk' {
  export interface AppApi {
    get: (path: string) => Promise<any>
    post: (path: string, body?: unknown) => Promise<any>
  }
  export function useAppApi(): AppApi
}

declare module '@kirocrew/app-sdk/ui' {
  import type { ReactNode, MouseEventHandler } from 'react'

  export interface CardProps {
    children?: ReactNode
    [key: string]: unknown
  }
  export function Card(props: CardProps): JSX.Element

  export interface PageHeaderProps {
    title?: ReactNode
    children?: ReactNode
    [key: string]: unknown
  }
  export function PageHeader(props: PageHeaderProps): JSX.Element

  export interface StatCardProps {
    label?: ReactNode
    value?: ReactNode
    children?: ReactNode
    [key: string]: unknown
  }
  export function StatCard(props: StatCardProps): JSX.Element

  export interface BtnProps {
    children?: ReactNode
    onClick?: MouseEventHandler
    [key: string]: unknown
  }
  export function Btn(props: BtnProps): JSX.Element
}
