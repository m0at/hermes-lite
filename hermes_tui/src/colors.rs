use ratatui::style::Color;

// Gold theme (matches cli.py's default palette)
pub const GOLD: Color = Color::Rgb(0xFF, 0xD7, 0x00);
pub const AMBER: Color = Color::Rgb(0xFF, 0xBF, 0x00);
pub const BRONZE: Color = Color::Rgb(0xCD, 0x7F, 0x32);
pub const DARK_GOLD: Color = Color::Rgb(0xB8, 0x86, 0x0B);
pub const CREAM: Color = Color::Rgb(0xFF, 0xF8, 0xDC);

// Status colors
pub const SUCCESS: Color = Color::Rgb(0x32, 0xCD, 0x32); // lime green
pub const ERROR: Color = Color::Rgb(0xFF, 0x44, 0x44);
pub const WARNING: Color = Color::Rgb(0xFF, 0x8C, 0x00);
pub const INFO: Color = Color::Rgb(0x00, 0xCE, 0xD1); // turquoise

// UI element colors
pub const USER_MSG: Color = Color::Rgb(0x00, 0xBF, 0xFF);
pub const THINK_BLOCK: Color = Color::Rgb(0x88, 0x88, 0x88);
pub const TOOL_RUNNING: Color = Color::Yellow;
pub const TOOL_DONE: Color = SUCCESS;
pub const TOOL_FAIL: Color = ERROR;
pub const DIM: Color = Color::DarkGray;
pub const SEPARATOR: Color = BRONZE;
